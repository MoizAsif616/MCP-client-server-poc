"""Verify the owned stop/start lifecycle and persistence using synthetic data."""

import asyncio
import json
import secrets
import socket
import sys
from pathlib import Path

import httpx2

from client.config import ServerConfig
from client.connection import connect
from tests.helpers import browser_login, hidden, login, signup

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "runtime" / "ngrok" / "state.json"


async def command(*arguments, expected=0):
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "scripts.ngrok", *arguments,
                                                  cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    output, error = await asyncio.wait_for(process.communicate(), timeout=110)
    assert process.returncode == expected, (output.decode(), error.decode())


async def local_health():
    results = {}
    async with httpx2.AsyncClient(timeout=1) as http:
        for port in (8000, 8002):
            try:
                response = await http.get(f"http://127.0.0.1:{port}/health")
                if response.status_code == 200:
                    results[str(port)] = response.json()
            except httpx2.HTTPError:
                pass
    return results


async def main():
    initial = json.loads(STATE.read_text())
    assert initial["status"] == "ready"
    origin = initial["public_url"]
    email = "ngrok-demo-" + secrets.token_hex(5) + "@example.test"
    password = "demo-pass"
    root = ROOT / "runtime" / "ngrok-lifecycle"
    root.mkdir(parents=True, exist_ok=True)
    cfg = ServerConfig("persistence", origin + "/mcp", callback_port=8887,
                       callback_url="http://127.0.0.1:8887/callback", token_dir=root / "tokens", log_dir=root / "client-logs")
    async with httpx2.AsyncClient() as browser:
        assert (await signup(browser, origin, email, ["calculator", "notes", "profile"])).status_code == 303
    async with connect(cfg, browser_login(email)) as sdk:
        profile = (await sdk.call_tool("get_profile", {})).structured_content
        assert not (await sdk.call_tool("save_note", {"text": "Persistent synthetic ngrok demonstration"})).is_error
    unchanged = await local_health()
    await command("--background", expected=1)
    assert json.loads(STATE.read_text())["run_id"] == initial["run_id"]
    await command("--stop")
    assert json.loads(STATE.read_text())["status"] == "stopped"
    for port in (initial["port"], initial["api_port"]):
        with socket.socket() as connection:
            assert connection.connect_ex(("127.0.0.1", port)) != 0, f"Owned port {port} did not close"
    assert await local_health() == unchanged
    with socket.socket() as owner:
        if sys.platform == "win32":
            owner.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        owner.bind(("127.0.0.1", initial["port"]))
        owner.listen()
        await command("--background", "--port", str(initial["port"]), "--api-port", str(initial["api_port"]), expected=1)
        assert "occupied" in json.loads(STATE.read_text())["error"]
        with socket.create_connection(("127.0.0.1", initial["port"]), timeout=1):
            pass
    await command("--background", "--port", str(initial["port"]), "--api-port", str(initial["api_port"]))
    restarted = json.loads(STATE.read_text())
    assert restarted["status"] == "ready" and restarted["run_id"] != initial["run_id"]
    assert restarted["database"] == initial["database"]
    assert restarted["access_token_seconds"] == 3600
    origin = restarted["public_url"]
    cfg.url = origin + "/mcp"
    async with httpx2.AsyncClient() as browser:
        assert (await login(browser, origin, email)).status_code == 303
        dashboard = await browser.get(origin)
        assert dashboard.status_code == 200 and email in dashboard.text
        assert (await browser.post(origin + "/logout", data={"csrf": hidden(dashboard.text, "csrf")})).status_code == 303
    async with connect(cfg, browser_login(email)) as sdk:
        assert (await sdk.call_tool("get_profile", {})).structured_content["id"] == profile["id"]
        assert "Persistent synthetic ngrok demonstration" in str((await sdk.call_tool("list_notes", {})).structured_content)
        assert (await sdk.call_tool("add", {"a": 20, "b": 22})).structured_content["result"] == 42
    assert await local_health() == unchanged
    report = {"checks": {"duplicate_start_rejected": True, "owned_backend_and_agent_stopped": True,
                         "occupied_backend_port_rejected_without_killing_owner": True,
                         "owned_ports_closed": True, "other_local_backends_preserved": True,
                         "restart_without_token_entry": True, "persistent_account_and_note": True,
                         "normal_token_lifetime_restored": True, "restarted_https_sdk_call": True},
              "public_url": origin, "mcp_url": origin + "/mcp", "database": restarted["database"],
              "demo_email": email, "demo_password": password, "preserved_local_services": unchanged,
              "claude_ai_live_integration": "Prepared for user; not performed"}
    (ROOT / "runtime" / "ngrok-lifecycle.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
