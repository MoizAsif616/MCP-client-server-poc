import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.processes import stop_process


def latest_tunnel_url(content):
    matches = re.findall(r"tunneled with tls termination,\s*(https://[a-z0-9.-]+)", content)
    return matches[-1] if matches else None


def start_backend(url, port, database, runtime):
    env = os.environ | {"PUBLIC_URL": url, "PORT": str(port), "DATABASE": str(database),
                        "LOG_DIR": str(ROOT / "logs" / "public-backend")}
    output = (runtime / "public-backend.out").open("a", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen([sys.executable, "-m", "backend"], cwd=ROOT, env=env,
                               stdout=output, stderr=output, creationflags=flags)
    for _ in range(100):
        if process.poll() is not None:
            break
        try:
            if httpx2.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return process, output
        except httpx2.HTTPError:
            pass
        time.sleep(0.1)
    stop_process(process)
    output.close()
    raise RuntimeError("Public backend failed to start; inspect runtime/public-backend.out")


def publish_url(url, port, database, backend, tunnel, runtime):
    config = {"servers": [{"name": "public", "url": url + "/mcp"}]}
    (ROOT / "client" / "servers-public.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (runtime / "public-url.json").write_text(json.dumps({"public_url": url, "mcp_url": url + "/mcp",
        "backend_pid": backend.pid, "tunnel_pid": tunnel.pid, "port": port,
        "database": str(database)}, indent=2), encoding="utf-8")
    print(f"\nWebsite: {url}\nClaude.ai MCP URL: {url}/mcp\n", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Free HTTPS tunnel plus local backend; no account required.")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    runtime = ROOT / "runtime"
    runtime.mkdir(exist_ok=True)
    log_path = runtime / "tunnel.log"
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
               "-o", f"UserKnownHostsFile={runtime / 'tunnel-known-hosts'}",
               "-o", "ServerAliveInterval=30", "-o", "ExitOnForwardFailure=yes",
               "-R", f"80:127.0.0.1:{args.port}", "nokey@localhost.run"]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    backend, backend_output = None, None
    with log_path.open("w", encoding="utf-8") as output:
        tunnel = subprocess.Popen(command, stdout=output, stderr=output, creationflags=flags)
        try:
            url = None
            for _ in range(120):
                if tunnel.poll() is not None:
                    raise RuntimeError("Tunnel stopped: " + log_path.read_text(encoding="utf-8"))
                content = log_path.read_text(encoding="utf-8", errors="replace")
                url = latest_tunnel_url(content)
                if url:
                    break
                time.sleep(0.5)
            if not url:
                raise RuntimeError("No public URL after 60 seconds; inspect runtime/tunnel.log")
            demo_dir = runtime / "public-demo" / secrets.token_hex(8)
            demo_dir.mkdir(parents=True)
            database = demo_dir / "app.sqlite3"
            backend, backend_output = start_backend(url, args.port, database, runtime)
            publish_url(url, args.port, database, backend, tunnel, runtime)
            print("Client: python -m client --config client/servers-public.json list", flush=True)
            print("Keep this command running. Ctrl+C stops its backend and tunnel.", flush=True)
            print("Uses a fresh demo database. Sign up on the public website with demo credentials.", flush=True)
            while tunnel.poll() is None and backend.poll() is None:
                time.sleep(1)
                current = latest_tunnel_url(log_path.read_text(encoding="utf-8", errors="replace"))
                if current and current != url:
                    stop_process(backend)
                    backend_output.close()
                    url = current
                    backend, backend_output = start_backend(url, args.port, database, runtime)
                    publish_url(url, args.port, database, backend, tunnel, runtime)
                    print("Tunnel hostname changed. Update Claude.ai and reconnect with the new URL.", flush=True)
            raise RuntimeError("Backend or tunnel stopped; inspect runtime/public-backend.out and runtime/tunnel.log")
        except KeyboardInterrupt:
            print("Stopping public backend and tunnel.")
        finally:
            for process in (backend, tunnel):
                if process and process.poll() is None:
                    stop_process(process)
            if backend_output:
                backend_output.close()


if __name__ == "__main__":
    main()
