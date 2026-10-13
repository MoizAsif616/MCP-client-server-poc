import os
import subprocess
import socket
import secrets
import json
import sys
import time
from pathlib import Path

import httpx2
import pytest
from scripts.processes import stop_process

ROOT = Path(__file__).resolve().parents[1]
ROOT.joinpath("runtime").mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def servers(request):
    root = ROOT / "runtime" / "verification" / secrets.token_hex(8)
    root.mkdir(parents=True)
    processes, streams = [], []
    ports = []
    for _ in range(2):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            ports.append(listener.getsockname()[1])
    urls = [f"http://127.0.0.1:{port}" for port in ports]
    database = root / "users.sqlite3"

    def start(index):
        env = os.environ | {"PORT": str(ports[index]), "PUBLIC_URL": urls[index],
                            "SERVER_NAME": f"Verification {index + 1}", "DATABASE": str(database),
                            "LOG_DIR": str(root / f"server-{index + 1}"), "ACCESS_TOKEN_SECONDS": "4"}
        stream = (root / f"server-{index + 1}.out").open("a", encoding="utf-8")
        streams.append(stream)
        process = subprocess.Popen([sys.executable, "-m", "backend"], cwd=ROOT, env=env, stdout=stream, stderr=stream)
        processes.append(process)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError((root / f"server-{index + 1}.out").read_text())
            try:
                if httpx2.get(urls[index] + "/health", timeout=1).status_code == 200:
                    return process
            except httpx2.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("Test server did not start")

    start(0)
    start(1)
    report = request.config.getoption("xmlpath", default=None)
    if not report or Path(report).name == "test-results.xml":
        (ROOT / "runtime" / "latest-verification.json").write_text(json.dumps({"root": str(root), "urls": urls}, indent=2))
    yield {"urls": urls, "root": root, "database": database, "start": start, "stop": stop_process, "processes": processes}
    for process in processes:
        if process.poll() is None:
            stop_process(process)
    for stream in streams:
        stream.close()
