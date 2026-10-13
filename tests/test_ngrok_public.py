"""Opt-in tests against the real, running ngrok demo; uses only synthetic users."""

import asyncio
import json
import os
import secrets
from pathlib import Path

import httpx2
import pytest

from client.logging import RecordingTransport
from client.connection import connect
from client.storage import FileTokenStorage
from tests.helpers import browser_login
from tests import test_http as cases

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.getenv("NGROK_VERIFY") != "1", reason="requires a running ngrok demo")


@pytest.fixture(autouse=True)
def internet_timeouts(monkeypatch):
    original = httpx2.AsyncClient

    class PublicHTTPClient(original):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("timeout", 30)
            # Retry only establishing a TCP connection, never an HTTP form or tool call.
            if "transport" not in kwargs:
                kwargs["transport"] = httpx2.AsyncHTTPTransport(retries=2)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", PublicHTTPClient)


@pytest.fixture(scope="module")
def ngrok_server():
    state = json.loads((ROOT / "runtime" / "ngrok" / "state.json").read_text())
    assert state["status"] == "ready"
    root = ROOT / "runtime" / "ngrok-verification" / secrets.token_hex(8)
    root.mkdir(parents=True)
    server = {"urls": [state["public_url"]], "root": root,
              "callback_port": 8885,
              "database": Path(state["database"]), "access_token_seconds": state["access_token_seconds"],
              "backend_logs": ROOT / "logs" / "ngrok-backend"}
    (ROOT / "runtime" / "latest-ngrok-verification.json").write_text(json.dumps({
        "root": str(root), "public_url": state["public_url"],
        "backend_logs": str(server["backend_logs"])}, indent=2))
    return server


@pytest.mark.parametrize("roles", cases.COMBINATIONS)
async def test_public_roles_website_sdk_calls_and_hidden_tools(ngrok_server, roles):
    await cases.test_roles_website_discovery_calls_and_hidden_names(ngrok_server, roles)


async def test_public_signup_login_csrf(ngrok_server):
    await cases.test_signup_login_errors_csrf_and_credentials(ngrok_server)


async def test_public_user_isolation_and_invalid_arguments(ngrok_server):
    await cases.test_user_data_isolation_and_invalid_arguments(ngrok_server)


async def test_public_expiration_refresh_and_invalid_tokens(ngrok_server):
    await cases.test_missing_invalid_expired_tokens_and_cookie_separation(ngrok_server)


@pytest.mark.parametrize("method", ["none", "client_secret_post", "client_secret_basic"])
async def test_public_pkce_exchange_binding_and_replay(ngrok_server, method):
    await cases.test_oauth_code_pkce_bindings_refresh_and_replay(ngrok_server, method)


async def test_public_metadata_registration_and_consent_denial(ngrok_server):
    await cases.test_oauth_discovery_invalid_requests_deny_and_claude_registration(ngrok_server)


async def test_public_callback_state_and_issuer(ngrok_server):
    await cases.test_callback_state_and_sdk_issuer_validation(ngrok_server)


async def test_public_scope_client_redirect_binding(ngrok_server):
    await cases.test_oauth_scope_client_and_redirect_bindings(ngrok_server)


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18", "2025-11-25"])
async def test_public_mcp_protocol_versions(ngrok_server, version):
    await cases.test_claude_documented_protocol_versions_over_http(ngrok_server, version)


async def test_public_standalone_sdk_client(ngrok_server):
    await cases.test_client_runs_without_backend_files_and_returns_readable_errors(ngrok_server)


async def test_public_actual_http_and_tool_logs(ngrok_server):
    origin = ngrok_server["urls"][0]
    log = ngrok_server["root"] / "audit-client.jsonl"
    query = "?text=a%20b&repeat=1&repeat=2&sample=" + secrets.token_hex(8)
    url = origin + "/not-found" + query
    samples = [("application/json", '{"number":2,"bool":true,"null":null,"array":[1,"x"]}'),
               ("application/x-www-form-urlencoded", "a=two+words&repeat=1&repeat=2"),
               ("text/plain; charset=utf-8", "Exact text\nUnicode ✓")]
    async with httpx2.AsyncClient(transport=RecordingTransport(log)) as http:
        for content_type, body in samples:
            assert (await http.post(url, content=body.encode(), headers={"Content-Type": content_type})).status_code == 404
    await asyncio.sleep(0.1)
    client = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    backend = [json.loads(line) for line in (ngrok_server["backend_logs"] / "http.jsonl").read_text(encoding="utf-8").splitlines()]
    for content_type, body in samples:
        sent = next(row for row in client if row["direction"] == "sent_request" and row["body"] == body)
        received = next(row for row in backend if row["direction"] == "received_request" and row["url"] == url and row["body"] == body)
        assert sent["url"] == received["url"] == url
        assert sent["content_type"] == received["content_type"] == content_type
        assert ["content-type", content_type] in received["headers"]
    responses = [row for row in client if row["direction"] == "received_response"]
    served = [row for row in backend if row["direction"] == "sent_response" and row["url"] == url]
    assert len(responses) == len(served) == 3
    for response, server in zip(responses, served):
        assert response["status"] == server["status"] == 404
        assert response["body"] == server["body"] and response["content_type"] == server["content_type"]
    sdk = [json.loads(line) for line in (ngrok_server["root"] / "client-logs" / "http.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row.get("status") == 401 for row in sdk)
    assert any("code_verifier=" in row["body"] for row in sdk if isinstance(row["body"], str))
    assert any(row["url"].endswith("/token") and '"refresh_token"' in row["body"] for row in sdk if isinstance(row["body"], str))
    tools = [json.loads(line) for line in (ngrok_server["backend_logs"] / "tools.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row["outcome"] == "success" for row in tools)
    assert any(row["outcome"].startswith("denied:") for row in tools)
    assert all(set(row) == {"timestamp", "tool_name", "originating_client", "receiving_server", "authenticated_user", "outcome"} for row in tools)


async def test_public_endpoint_urls_origin_allowlist_and_wrong_audience(ngrok_server):
    import socket
    import subprocess
    import sys
    from scripts.processes import stop_process

    origin = ngrok_server["urls"][0]
    email = await cases.account(ngrok_server, ["calculator"])
    config = cases.config(ngrok_server, "allowlist")
    async with connect(config, browser_login(email)) as sdk:
        assert not (await sdk.call_tool("add", {"a": 20, "b": 22})).is_error
        access = FileTokenStorage(config).read()["tokens"]["access_token"]
        headers = {"Authorization": "Bearer " + access, "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-11-25", "Origin": origin}
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        async with httpx2.AsyncClient() as http:
            for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
                metadata = (await http.get(origin + path)).json()
                assert metadata["resource"] == origin + "/mcp" and metadata["authorization_servers"] == [origin]
            metadata = (await http.get(origin + "/.well-known/oauth-authorization-server")).json()
            assert metadata["issuer"] == origin
            for key, path in (("authorization_endpoint", "/authorize"), ("registration_endpoint", "/register"), ("token_endpoint", "/token")):
                assert metadata[key] == origin + path
            assert (await http.post(origin + "/mcp", headers=headers, json=message)).status_code == 200
            assert (await http.post(origin + "/mcp", headers=headers | {"Origin": "https://wrong.example"}, json=message)).status_code == 403

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    local = f"http://127.0.0.1:{port}"
    env = os.environ | {"PUBLIC_URL": local, "PORT": str(port), "DATABASE": str(ngrok_server["database"]),
                        "LOG_DIR": str(ngrok_server["root"] / "other-audience"), "ACCESS_TOKEN_SECONDS": "3600"}
    with (ngrok_server["root"] / "other-audience.out").open("w") as output:
        process = subprocess.Popen([sys.executable, "-m", "backend"], cwd=ROOT, env=env, stdout=output, stderr=output)
        try:
            async with httpx2.AsyncClient() as http:
                for _ in range(100):
                    assert process.poll() is None
                    try:
                        if (await http.get(local + "/health")).status_code == 200:
                            break
                    except httpx2.HTTPError:
                        pass
                    await asyncio.sleep(0.1)
            other = dict(ngrok_server, urls=[local])
            local_config = cases.config(other, "wrong_audience")
            async with connect(local_config, browser_login(email)) as sdk:
                assert not (await sdk.call_tool("add", {"a": 1, "b": 2})).is_error
                access = FileTokenStorage(local_config).read()["tokens"]["access_token"]
            async with httpx2.AsyncClient() as http:
                response = await http.post(origin + "/mcp", json=message, headers={"Authorization": "Bearer " + access})
                assert response.status_code == 401 and "different resource" in response.text
        finally:
            stop_process(process)
