import asyncio
import json
import secrets
from pathlib import Path

import httpx2

from client.config import ServerConfig
from client.connection import connect
from tests.helpers import browser_login, signup
from client.logging import RecordingTransport

ROOT = Path(__file__).resolve().parents[1]


async def main():
    public = json.loads((ROOT / "runtime" / "public-url.json").read_text())
    origin = public["public_url"]
    email = "tunnel-demo-" + secrets.token_hex(4) + "@example.test"
    checks = {}
    async with httpx2.AsyncClient(transport=RecordingTransport(ROOT / "logs" / "public-verification.jsonl")) as http:
        response = await http.get(origin + "/health")
        checks["https_health"] = response.status_code == 200
        response = await http.post(origin + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        checks["challenge"] = response.status_code == 401 and origin in response.headers["www-authenticate"]
        response = await http.get(origin + "/.well-known/oauth-protected-resource/mcp")
        checks["public_resource"] = response.json()["resource"] == origin + "/mcp"
        response = await http.get(origin + "/.well-known/oauth-authorization-server")
        checks["public_oauth_urls"] = all(response.json()[key].startswith(origin) for key in
                                         ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint"))
        response = await signup(http, origin, email, ["calculator", "profile"])
        checks["synthetic_signup"] = response.status_code == 303
    cfg = ServerConfig("public_verify", origin + "/mcp", token_dir=ROOT / "runtime" / "public-tokens",
                       callback_port=8766, callback_url="http://127.0.0.1:8766/callback",
                       log_dir=ROOT / "logs" / "public-client")
    async with connect(cfg, browser_login(email)) as sdk:
        tools = await sdk.list_tools()
        checks["https_oauth_and_discovery"] = {tool.name for tool in tools.tools} == {"add", "multiply", "get_profile"}
        result = await sdk.call_tool("add", {"a": 11, "b": 31})
        checks["https_tool_call"] = not result.is_error and result.structured_content["result"] == 42
        result = await sdk.call_tool("save_note", {"text": "synthetic"})
        checks["https_hidden_tool_denied"] = result.is_error
    assert all(checks.values()), checks
    report = {"public_url": origin, "checks": checks, "claude_ai_live_test": "not performed; user will test"}
    (ROOT / "runtime" / "public-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
