"""Run a dedicated demo backend through the installed ngrok agent."""

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.processes import stop_process

RUNTIME = ROOT / "runtime" / "ngrok"
STATE = RUNTIME / "state.json"
LOCK = RUNTIME / "controller.lock"
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def read_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def write_state(state):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(STATE)


def require_free_port(port):
    with socket.socket() as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(f"Loopback port {port} is occupied. Stop its owner or choose another port.") from None


def public_origin(tunnels, upstream):
    for tunnel in tunnels:
        url = tunnel.get("public_url", "")
        address = tunnel.get("config", {}).get("addr", "")
        if address.rstrip("/") != upstream.rstrip("/"):
            continue
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.hostname and parsed.path in {"", "/"} and not parsed.query:
            return url.rstrip("/")
    return None


def stop_request(run_id):
    return RUNTIME / f"stop-{run_id}"


def acquire_lock():
    lock = LOCK.open("a+b")
    try:
        if lock.seek(0, 2) == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock
    except OSError:
        lock.close()
        raise RuntimeError("An ngrok demo controller is already running. Use --stop first.") from None


def stop():
    state = read_state()
    if state.get("status") == "stop_failed":
        raise RuntimeError(state["error"] + " Inspect these owned processes before starting again.")
    if state.get("status") not in {"starting", "ready"}:
        print("No active ngrok demo controller.")
        return
    stop_request(state["run_id"]).touch()
    for _ in range(120):
        current = read_state()
        if current.get("run_id") != state["run_id"] or current.get("status") == "stopped":
            print("Stopped the demo backend and its ngrok agent.")
            return
        time.sleep(0.25)
    raise RuntimeError("The controller did not acknowledge stop. No unrelated process was killed.")


def agent_path():
    executable = shutil.which("ngrok")
    if not executable:
        raise RuntimeError("ngrok is not installed or available on PATH. Install it with winget install ngrok -s msstore.")
    return executable


def wait_health(url, processes, stop_file, seconds=45):
    deadline = time.monotonic() + seconds
    with httpx2.Client(timeout=3, headers={"ngrok-skip-browser-warning": "1"}) as http:
        while time.monotonic() < deadline:
            if stop_file.exists():
                raise RuntimeError("Startup stopped by request.")
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("An owned process stopped during startup.")
            try:
                response = http.get(url + "/health")
                if response.status_code == 200 and response.json().get("status") == "ok":
                    return
            except (httpx2.HTTPError, ValueError):
                pass
            time.sleep(0.3)
    raise RuntimeError("The backend or public HTTPS health check timed out.")


def run(args):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or secrets.token_hex(12)
    stop_file = stop_request(run_id)
    processes, streams, error_codes = [], [], set()
    state = {"run_id": run_id, "controller_pid": os.getpid(), "status": "starting",
             "port": args.port, "api_port": args.api_port,
             "database": str(ROOT / "data" / "ngrok-demo.sqlite3"),
             "access_token_seconds": args.access_token_seconds}
    lock = acquire_lock()
    try:
        write_state(state)
        if args.port == args.api_port:
            raise RuntimeError("Backend and ngrok API ports must be different.")
        for port in (args.port, args.api_port):
            require_free_port(port)
        credentials = Path(os.environ["LOCALAPPDATA"]) / "ngrok" / "ngrok-poc.yml"
        if not credentials.is_file():
            raise RuntimeError("Missing private ngrok-poc.yml configuration in your per-user ngrok folder.")
        overlay = RUNTIME / "agent-options.yml"
        overlay.write_text(f"version: 2\nweb_addr: 127.0.0.1:{args.api_port}\n", encoding="utf-8")
        upstream = f"http://127.0.0.1:{args.port}"
        command = [agent_path(), "http", upstream, "--config", str(credentials), "--config", str(overlay),
                   "--log=false", "--inspect=false"]
        # Drain agent diagnostics in memory; retain only safe documented error identifiers.
        agent = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=FLAGS)
        processes.append(agent)

        def drain():
            for line in agent.stdout:
                error_codes.update(re.findall(r"ERR_NGROK_[0-9]+", line.decode("utf-8", errors="replace")))

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        deadline = time.monotonic() + 45
        origin = None
        with httpx2.Client(timeout=1) as http:
            while time.monotonic() < deadline and agent.poll() is None and not stop_file.exists():
                try:
                    response = http.get(f"http://127.0.0.1:{args.api_port}/api/tunnels")
                    if response.status_code == 200:
                        origin = public_origin(response.json().get("tunnels", []), upstream)
                        if origin:
                            break
                except (httpx2.HTTPError, ValueError):
                    pass
                time.sleep(0.2)
        if not origin:
            reader.join(timeout=0.5)
            codes = ", ".join(sorted(error_codes)) or "no safe agent error code available"
            raise RuntimeError(f"ngrok could not establish a tunnel ({codes}). Credential values are suppressed.")
        env = os.environ | {"PORT": str(args.port), "PUBLIC_URL": origin, "DATABASE": state["database"],
                            "LOG_DIR": str(ROOT / "logs" / "ngrok-backend"),
                            "ACCESS_TOKEN_SECONDS": str(args.access_token_seconds), "SERVER_NAME": "Ngrok demo MCP"}
        output = (RUNTIME / "backend.out").open("a", encoding="utf-8")
        streams.append(output)
        backend = subprocess.Popen([sys.executable, "-m", "backend"], cwd=ROOT, env=env,
                                   stdout=output, stderr=output, creationflags=FLAGS)
        processes.append(backend)
        wait_health(upstream, processes, stop_file)
        wait_health(origin, processes, stop_file)
        config = {"servers": [{"name": "ngrok", "url": origin + "/mcp",
                              "token_dir": str(ROOT / "client" / "tokens" / "ngrok"),
                              "log_dir": str(ROOT / "logs" / "ngrok-client")}]}
        (ROOT / "client" / "servers-ngrok.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        state.update(status="ready", public_url=origin, mcp_url=origin + "/mcp",
                     backend_pid=backend.pid, agent_pid=agent.pid)
        write_state(state)
        print(f"Ready. Website: {origin}\nMCP: {origin}/mcp", flush=True)
        print("Stop: .\\.venv\\Scripts\\python.exe -m scripts.ngrok --stop", flush=True)
        while not stop_file.exists():
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("The demo backend or its ngrok agent stopped.")
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("Stopping the ngrok demo.", flush=True)
    except Exception as exc:
        state["error"] = str(exc)
        raise
    finally:
        cleanup_errors = []
        for process in reversed(processes):
            try:
                stop_process(process)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_errors.append(f"Owned process {process.pid} did not stop.")
        for stream in streams:
            stream.close()
        state["status"] = "stop_failed" if cleanup_errors else "stopped"
        if cleanup_errors:
            state["error"] = " ".join(cleanup_errors)
        try:
            write_state(state)
            stop_file.unlink(missing_ok=True)
        finally:
            # OS locks release even if the controller crashes; the file may safely remain.
            lock.close()
        if cleanup_errors:
            raise RuntimeError(state["error"])


def background(args):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    acquire_lock().close()
    run_id = secrets.token_hex(12)
    command = [sys.executable, "-m", "scripts.ngrok", "--run-id", run_id, "--port", str(args.port),
               "--api-port", str(args.api_port), "--access-token-seconds", str(args.access_token_seconds)]
    with (RUNTIME / "launcher.out").open("a", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=output, creationflags=FLAGS)
    for _ in range(400):
        state = read_state()
        if state.get("run_id") == run_id and state.get("status") == "ready":
            print(f"Ready. Website: {state['public_url']}\nMCP: {state['mcp_url']}")
            return
        if process.poll() is not None:
            raise RuntimeError(state.get("error", "Controller failed to start; inspect runtime/ngrok/launcher.out."))
        time.sleep(0.25)
    stop_request(run_id).touch()
    raise RuntimeError("Background startup timed out; a stop request was sent to this controller.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--background", action="store_true")
    actions.add_argument("--stop", action="store_true")
    actions.add_argument("--status", action="store_true")
    parser.add_argument("--port", type=int, default=8004)
    parser.add_argument("--api-port", type=int, default=4041)
    parser.add_argument("--access-token-seconds", type=int, default=3600)
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.port < 65536 or not 0 < args.api_port < 65536 or args.access_token_seconds < 1:
        parser.error("Ports must be 1-65535 and token lifetime must be positive.")
    try:
        if args.stop:
            stop()
        elif args.status:
            print(json.dumps(read_state(), indent=2))
        elif args.background:
            background(args)
        else:
            run(args)
    except (RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
