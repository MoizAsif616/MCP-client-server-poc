import asyncio
import itertools
import json
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from client.config import ServerConfig
from client.connection import connect
from client.routing import ToolRouter
from client.storage import FileTokenStorage
from tests.helpers import auth_params, browser_login, get_code, grant, hidden, login, register, signup

ROLES = {"calculator": {"add", "multiply"}, "notes": {"save_note", "list_notes"}, "profile": {"get_profile"}}
COMBINATIONS = [combo for count in (1, 2, 3) for combo in itertools.combinations(ROLES, count)]


def config(servers, name, index=0):
    callback_port = servers.get("callback_port", 8865)
    return ServerConfig(name=name, url=servers["urls"][index] + "/mcp",
                        callback_port=callback_port, callback_url=f"http://127.0.0.1:{callback_port}/callback",
                        token_dir=servers["root"] / "client-tokens", log_dir=servers["root"] / "client-logs")


async def account(servers, roles):
    email = secrets.token_hex(6) + "@example.test"
    async with httpx2.AsyncClient() as browser:
        response = await signup(browser, servers["urls"][0], email, roles)
        assert response.status_code == 303
    return email


@pytest.mark.parametrize("roles", COMBINATIONS)
async def test_roles_website_discovery_calls_and_hidden_names(servers, roles):
    email = await account(servers, roles)
    origin = servers["urls"][0]
    async with httpx2.AsyncClient() as browser:
        assert (await login(browser, origin, email)).status_code == 303
        dashboard = await browser.get(origin)
        assert dashboard.status_code == 200
        allowed = set().union(*(ROLES[r] for r in roles))
        for name in set().union(*ROLES.values()):
            assert (f"<strong>{name}</strong>" in dashboard.text) == (name in allowed)
        for role in roles:
            assert role.title() in dashboard.text
        assert origin + "/mcp" in dashboard.text
        assert (await browser.post(origin + "/logout", data={"csrf": hidden(dashboard.text, "csrf")})).status_code == 303
        assert (await browser.get(origin)).status_code == 303
    cfg = config(servers, "roles_" + "_".join(roles))
    async with connect(cfg, browser_login(email)) as sdk:
        tools = await sdk.list_tools()
        assert {tool.name for tool in tools.tools} == allowed
        arguments = {"add": {"a": 2, "b": 3}, "multiply": {"a": 4, "b": 5},
                     "save_note": {"text": "Private note ✓"}, "list_notes": {}, "get_profile": {}}
        for name in allowed:
            result = await sdk.call_tool(name, arguments[name])
            assert not result.is_error, result
            if name == "add":
                assert result.structured_content["result"] == 5
            if name == "multiply":
                assert result.structured_content["result"] == 20
            if name == "get_profile":
                assert result.structured_content["email"] == email
                assert set(result.structured_content["roles"]) == set(roles)
        for name in set().union(*ROLES.values()) - allowed:
            result = await sdk.call_tool(name, arguments[name])
            assert result.is_error and "does not permit" in result.content[0].text
        unknown = await sdk.call_tool("unknown_tool", {})
        assert unknown.is_error


async def test_signup_login_errors_csrf_and_credentials(servers):
    origin = servers["urls"][0]
    email = await account(servers, ["notes"])
    async with httpx2.AsyncClient() as browser:
        assert (await signup(browser, origin, email, ["notes"])).status_code == 409
        assert (await signup(browser, origin, "invalid", ["notes"])).status_code == 400
        assert (await signup(browser, origin, "empty@example.test", [])).status_code == 400
        assert (await signup(browser, origin, "role@example.test", ["admin"])).status_code == 400
        assert (await login(browser, origin, email, "wrong-password")).status_code == 401
        assert (await browser.post(origin + "/login", data={"email": email, "password": "demo-pass"})).status_code == 403
        assert (await login(browser, origin, email)).status_code == 303
        assert (await browser.post(origin + "/logout", data={"csrf": "bad"})).status_code == 403
        assert (await browser.get(origin)).status_code == 200


async def test_user_data_isolation_and_invalid_arguments(servers):
    first = await account(servers, ["notes", "profile", "calculator"])
    second = await account(servers, ["notes", "profile"])
    async with connect(config(servers, "owner_a"), browser_login(first)) as sdk:
        profile = (await sdk.call_tool("get_profile", {})).structured_content
        assert not (await sdk.call_tool("save_note", {"text": "first-only"})).is_error
        assert "first-only" in str((await sdk.call_tool("list_notes", {})).structured_content)
        for name, arguments in [("add", {"a": "abc", "b": 2}), ("add", {"a": 1}),
                                ("save_note", {"text": ""}), ("save_note", {"text": 123})]:
            try:
                result = await sdk.call_tool(name, arguments)
                assert result.is_error
            except Exception as exc:
                assert "valid" in str(exc).lower() or "required" in str(exc).lower() or "schema" in str(exc).lower()
    async with connect(config(servers, "owner_b"), browser_login(second)) as sdk:
        notes = await sdk.call_tool("list_notes", {})
        assert notes.structured_content["notes"] == []
        for name in ("list_notes", "get_profile"):
            result = await sdk.call_tool(name, {"user_id": profile["id"]})
            assert result.is_error and "own data" in result.content[0].text


async def test_missing_invalid_expired_tokens_and_cookie_separation(servers):
    origin = servers["urls"][0]
    email = await account(servers, ["calculator"])
    cfg = config(servers, "expiry")
    async with connect(cfg, browser_login(email)) as sdk:
        assert not (await sdk.call_tool("add", {"a": 1, "b": 2})).is_error
    stored = FileTokenStorage(cfg).read()
    access = stored["tokens"]["access_token"]
    async with httpx2.AsyncClient() as http:
        for header in ({}, {"Authorization": "Bearer invalid"}):
            response = await http.post(origin + "/mcp", headers=header, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            assert response.status_code == 401
            assert 'resource_metadata="' in response.headers["www-authenticate"]
        assert (await login(http, origin, email)).status_code == 303
        assert (await http.post(origin + "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})).status_code == 401
        await asyncio.sleep(servers.get("access_token_seconds", 4) + 0.2)
        response = await http.post(origin + "/mcp", headers={"Authorization": "Bearer " + access}, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        assert response.status_code == 401
    async def no_browser(url):
        raise AssertionError("A refresh must not require browser login")
    async with connect(cfg, no_browser) as sdk:
        assert not (await sdk.call_tool("multiply", {"a": 3, "b": 4})).is_error
    refreshed = FileTokenStorage(cfg).read()
    assert refreshed["tokens"]["access_token"] != access
    assert refreshed["tokens"]["refresh_token"] != stored["tokens"]["refresh_token"]
    async with httpx2.AsyncClient() as http:
        response = await http.post(origin + "/token", data={"grant_type": "refresh_token",
            "client_id": stored["client_info"]["client_id"], "refresh_token": stored["tokens"]["refresh_token"],
            "resource": origin + "/mcp"})
        assert response.status_code == 400 and response.json()["error"] == "invalid_grant"


@pytest.mark.parametrize("method", ["none", "client_secret_post", "client_secret_basic"])
async def test_oauth_code_pkce_bindings_refresh_and_replay(servers, method):
    origin = servers["urls"][0]
    email = await account(servers, ["calculator"])
    async with httpx2.AsyncClient() as browser:
        assert (await login(browser, origin, email)).status_code == 303
        client = await register(browser, origin, method)
        params, verifier = auth_params(client, origin)
        values = await get_code(browser, origin, params)
        assert values["state"] == [params["state"]] and values["iss"] == [origin]
        bad = await grant(browser, origin, client, params, "a" * 64, values["code"][0])
        assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
        response = await grant(browser, origin, client, params, verifier, values["code"][0])
        assert response.status_code == 200, response.text
        tokens = response.json()
        assert response.headers["cache-control"] == "no-store"
        assert (await grant(browser, origin, client, params, verifier, values["code"][0])).status_code == 400
        data = {"grant_type": "refresh_token", "client_id": client["client_id"],
                "refresh_token": tokens["refresh_token"], "resource": origin + "/mcp"}
        auth = None
        if method == "client_secret_post":
            data["client_secret"] = client["client_secret"]
        if method == "client_secret_basic":
            auth = httpx2.BasicAuth(client["client_id"], client["client_secret"])
        bad_resource = await browser.post(origin + "/token", data=data | {"resource": origin + "/wrong"}, auth=auth)
        assert bad_resource.status_code == 400 and bad_resource.json()["error"] == "invalid_target"
        refresh = await browser.post(origin + "/token", data=data, auth=auth)
        assert refresh.status_code == 200 and refresh.json()["refresh_token"] != tokens["refresh_token"]
        assert (await browser.post(origin + "/token", data=data, auth=auth)).json()["error"] == "invalid_grant"


async def test_oauth_discovery_invalid_requests_deny_and_claude_registration(servers):
    origin = servers["urls"][0]
    email = await account(servers, ["profile"])
    async with httpx2.AsyncClient() as browser:
        resource = (await browser.get(origin + "/.well-known/oauth-protected-resource/mcp")).json()
        metadata = (await browser.get(origin + "/.well-known/oauth-authorization-server")).json()
        assert resource["resource"] == origin + "/mcp"
        assert resource["authorization_servers"] == [origin]
        assert metadata["issuer"] == origin and metadata["code_challenge_methods_supported"] == ["S256"]
        claude = await register(browser, origin, callback="https://claude.ai/api/mcp/auth_callback")
        assert claude["token_endpoint_auth_method"] == "none"
        client = await register(browser, origin)
        params, _ = auth_params(client, origin)
        for changes in ({"redirect_uri": "https://evil.test"}, {"code_challenge_method": "plain"},
                        {"resource": "https://other.test/mcp"}, {"scope": "admin"}, {"state": ""},
                        {"client_id": "missing"}):
            response = await browser.get(origin + "/authorize", params=params | changes)
            assert response.status_code == 400
        assert (await login(browser, origin, email)).status_code == 303
        values = await get_code(browser, origin, params, decision="deny")
        assert values["error"] == ["access_denied"] and "code" not in values
        invalid = await browser.post(origin + "/register", json={"redirect_uris": ["http://remote.test/callback"]})
        assert invalid.status_code == 400


async def test_callback_state_and_sdk_issuer_validation(servers):
    from client.authentication import CallbackListener
    from mcp.client.auth.utils import validate_authorization_response_iss
    from mcp.shared.auth import OAuthMetadata
    from mcp.client.auth.exceptions import OAuthFlowError
    cfg = config(servers, "callback")
    with CallbackListener(cfg) as listener:
        listener.expected_state = "expected-state"
        async with httpx2.AsyncClient() as browser:
            response = await browser.get(cfg.callback_url, params={"code": "unused", "state": "wrong"})
            assert response.status_code == 400 and listener.result.empty()
            response = await browser.get(cfg.callback_url + "/wrong", params={"state": "expected-state"})
            assert response.status_code == 400
    origin = servers["urls"][0]
    async with httpx2.AsyncClient() as http:
        metadata = OAuthMetadata.model_validate((await http.get(origin + "/.well-known/oauth-authorization-server")).json())
    with pytest.raises(OAuthFlowError):
        validate_authorization_response_iss("https://wrong.test", metadata)
    with pytest.raises(OAuthFlowError):
        validate_authorization_response_iss(None, metadata)
    validate_authorization_response_iss(origin, metadata)


async def test_multi_server_routing_resource_binding_and_persistence(servers):
    email = await account(servers, ["profile", "calculator"])
    configs = [config(servers, "first", 0), config(servers, "second", 1)]
    router = ToolRouter(configs, browser_login(email))
    tools = await router.discover()
    assert not router.errors, router.errors
    assert set(tools) == {f"{s}:{t}" for s in ("first", "second") for t in ("add", "multiply", "get_profile")}
    assert (await router.call("first:add", {"a": 2, "b": 6})).structured_content["result"] == 8
    assert (await router.call("second:multiply", {"a": 2, "b": 6})).structured_content["result"] == 12
    token = FileTokenStorage(configs[0]).read()["tokens"]["access_token"]
    async with httpx2.AsyncClient() as http:
        response = await http.post(configs[1].url, headers={"Authorization": "Bearer " + token}, json={"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
        assert response.status_code == 401 and "different resource" in response.text
    servers["stop"](servers["processes"][1])
    servers["start"](1)
    async with httpx2.AsyncClient() as browser:
        assert (await login(browser, servers["urls"][1], email)).status_code == 303
        assert email in (await browser.get(servers["urls"][1])).text
    assert (await router.call("second:get_profile", {})).structured_content["email"] == email


async def test_exact_logs_json_form_text_and_tool_outcomes(servers):
    from client.logging import RecordingTransport
    origin = servers["urls"][0]
    log = servers["root"] / "audit-client.jsonl"
    samples = [("application/json", '{"number":2,"bool":true,"null":null, "array":[1,"x"]}'),
               ("application/x-www-form-urlencoded", "a=two+words&repeat=1&repeat=2&token=demo-secret"),
               ("text/plain; charset=utf-8", "Hello\nexact text ✓")]
    async with httpx2.AsyncClient(transport=RecordingTransport(log)) as http:
        for content_type, body in samples:
            response = await http.post(origin + "/not-found?first=a%20b&second=2", content=body.encode(), headers={"Content-Type": content_type})
            assert response.status_code == 404
    await asyncio.sleep(0.1)
    client_rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    server_rows = [json.loads(line) for line in (servers["root"] / "server-1" / "http.jsonl").read_text(encoding="utf-8").splitlines()]
    for content_type, body in samples:
        sent = next(row for row in client_rows if row["direction"] == "sent_request" and row["body"] == body)
        received = next(row for row in server_rows if row["direction"] == "received_request" and row["body"] == body)
        assert sent["url"] == received["url"] == origin + "/not-found?first=a%20b&second=2"
        assert [[k.lower(), v] for k, v in sent["headers"]] == received["headers"]
        assert received["content_type"] == content_type
    client_responses = [row for row in client_rows if row["direction"] == "received_response"]
    server_responses = [row for row in server_rows if row["direction"] == "sent_response" and "/not-found?" in row["url"]]
    for client_row, server_row in zip(client_responses, server_responses):
        assert client_row["status"] == server_row["status"]
        assert client_row["body"] == server_row["body"]
        assert client_row["headers"] == server_row["headers"]
    rows = [json.loads(line) for line in (servers["root"] / "client-logs" / "http.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row["status"] == 401 for row in rows if "status" in row)
    assert any("code_verifier=" in row["body"] for row in rows if isinstance(row["body"], str))
    assert any(row["url"].endswith("/token") and '"refresh_token"' in row["body"] for row in rows if isinstance(row["body"], str))
    assert any(key.lower() == "authorization" and value.startswith("Bearer ") for row in rows for key, value in row["headers"])
    tool_rows = [json.loads(line) for line in (servers["root"] / "server-1" / "tools.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row["outcome"] == "success" for row in tool_rows)
    assert any(row["outcome"].startswith("denied:") for row in tool_rows)
    assert any(row["outcome"].startswith("error:") or row["outcome"] == "tool_error" for row in tool_rows)
    assert all(set(row) == {"timestamp", "tool_name", "originating_client", "receiving_server", "authenticated_user", "outcome"} for row in tool_rows)


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18", "2025-11-25"])
async def test_claude_documented_protocol_versions_over_http(servers, version):
    origin = servers["urls"][0]
    email = await account(servers, ["calculator"])
    async with httpx2.AsyncClient() as browser:
        assert (await login(browser, origin, email)).status_code == 303
        client = await register(browser, origin)
        params, verifier = auth_params(client, origin)
        code = (await get_code(browser, origin, params))["code"][0]
        response = await grant(browser, origin, client, params, verifier, code)
        access = response.json()["access_token"]
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + access,
        "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": version}) as http:
        response = await http.post(origin + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "compatibility-check", "version": "1"}}})
        assert response.status_code == 200 and response.json()["result"]["protocolVersion"] == version
        response = await http.post(origin + "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert response.status_code == 202
        response = await http.post(origin + "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == {"add", "multiply"}
        response = await http.post(origin + "/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "add", "arguments": {"a": 19, "b": 23}}})
        assert not response.json()["result"]["isError"]
        assert "42" in response.json()["result"]["content"][0]["text"]


async def test_oauth_scope_client_and_redirect_bindings(servers):
    origin = servers["urls"][0]
    email = await account(servers, ["calculator"])
    async with httpx2.AsyncClient() as browser:
        assert (await login(browser, origin, email)).status_code == 303
        client = await register(browser, origin)
        other = await register(browser, origin)
        params, verifier = auth_params(client, origin)
        code = (await get_code(browser, origin, params))["code"][0]
        assert (await grant(browser, origin, other, params, verifier, code)).json()["error"] == "invalid_grant"
        bad = params | {"redirect_uri": "http://127.0.0.1:9876/wrong"}
        assert (await grant(browser, origin, client, bad, verifier, code)).json()["error"] == "invalid_grant"
        response = await grant(browser, origin, client, params, verifier, code)
        tokens = response.json()
        data = {"grant_type": "refresh_token", "client_id": client["client_id"],
                "refresh_token": tokens["refresh_token"], "resource": origin + "/mcp"}
        response = await browser.post(origin + "/token", data=data | {"scope": "tools admin"})
        assert response.json()["error"] == "invalid_scope"
        response = await browser.post(origin + "/token", data=data | {"client_id": other["client_id"]})
        assert response.json()["error"] == "invalid_grant"
        response = await browser.post(origin + "/register", json={"redirect_uris": ["http://127.0.0.1:9876/callback"], "scope": ["tools"]})
        assert response.status_code == 400 and response.json()["error"] == "invalid_scope"


async def test_client_runs_without_backend_files_and_returns_readable_errors(servers):
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    project = Path(__file__).resolve().parents[1]
    isolated = servers["root"] / "standalone-client"
    shutil.copytree(project / "client", isolated / "client", ignore=shutil.ignore_patterns("__pycache__", "tokens"))
    email = await account(servers, ["calculator"])
    cfg = config(servers, "standalone")
    async with connect(cfg, browser_login(email)) as sdk:
        assert {tool.name for tool in (await sdk.list_tools()).tools} == {"add", "multiply"}
    settings = {"servers": [{"name": cfg.name, "url": cfg.url, "token_dir": str(cfg.token_dir),
                             "log_dir": str(cfg.log_dir), "callback_port": cfg.callback_port,
                             "callback_url": cfg.callback_url}]}
    config_file = isolated / "servers.json"
    config_file.write_text(json.dumps(settings), encoding="utf-8")
    assert not (isolated / "backend").exists()
    command = [sys.executable, "-m", "client", "--config", str(config_file), "call"]
    env = os.environ | {"PYTHONIOENCODING": "utf-8", "PYTHONPATH": ""}
    success = await asyncio.to_thread(subprocess.run, command + ["standalone:add", "--args", '{"a":20,"b":22}'],
                                      cwd=isolated, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert success.returncode == 0, success.stderr
    assert json.loads(success.stdout)["result"] == 42
    denied = await asyncio.to_thread(subprocess.run, command + ["standalone:save_note", "--args", '{"text":"hidden"}'],
                                     cwd=isolated, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert denied.returncode == 2 and "does not permit" in denied.stdout
    invalid = await asyncio.to_thread(subprocess.run, command + ["standalone:add", "--args", '{"a":"oops","b":2}'],
                                      cwd=isolated, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert invalid.returncode != 0 and ("valid" in invalid.stdout.lower() or "valid" in invalid.stderr.lower())


async def test_actual_streaming_and_server_error_logs(servers):
    import os
    import socket
    import subprocess
    import sys
    from pathlib import Path
    from client.logging import RecordingTransport
    from scripts.processes import stop_process
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    server_log = servers["root"] / "streaming-server.jsonl"
    client_log = servers["root"] / "streaming-client.jsonl"
    env = os.environ | {"FIXTURE_LOG": str(server_log)}
    with (servers["root"] / "streaming.out").open("w") as output:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.fixture_app:app", "--host", "127.0.0.1",
            "--port", str(port), "--no-server-header", "--no-date-header"],
            cwd=Path(__file__).resolve().parents[1], env=env, stdout=output, stderr=output)
        try:
            async with httpx2.AsyncClient(transport=RecordingTransport(client_log)) as http:
                for _ in range(100):
                    try:
                        if (await http.get(origin + "/health")).status_code == 200:
                            break
                    except httpx2.HTTPError:
                        await asyncio.sleep(0.1)
                response = await http.get(origin + "/stream?exact=a%20b")
                assert response.text == 'event: message\ndata: {"value":2}\n\nevent: message\ndata: {"value":true}\n\n'
                assert (await http.get(origin + "/crash")).status_code == 500
            await asyncio.sleep(0.1)
            client_rows = [json.loads(line) for line in client_log.read_text().splitlines()]
            server_rows = [json.loads(line) for line in server_log.read_text().splitlines()]
            for endpoint, status in (("/stream?exact=a%20b", 200), ("/crash", 500)):
                c = next(row for row in client_rows if row.get("status") == status and row["url"] == origin + endpoint)
                s = next(row for row in server_rows if row.get("status") == status and row["url"] == origin + endpoint)
                assert c["body"] == s["body"] and c["content_type"] == s["content_type"]
        finally:
            stop_process(process)
