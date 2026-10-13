import socket
import secrets

import pytest

from scripts import ngrok
from scripts.ngrok import public_origin, require_free_port


def test_occupied_port_is_rejected_without_stopping_its_owner():
    with socket.socket() as owner:
        owner.bind(("127.0.0.1", 0))
        owner.listen()
        port = owner.getsockname()[1]
        with pytest.raises(RuntimeError, match="occupied"):
            require_free_port(port)
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    require_free_port(port)


def test_agent_discovery_only_selects_own_https_upstream():
    tunnels = [
        {"public_url": "https://unrelated.example", "config": {"addr": "http://127.0.0.1:8000"}},
        {"public_url": "http://demo.example", "config": {"addr": "http://127.0.0.1:8004"}},
        {"public_url": "https://demo.example", "config": {"addr": "http://127.0.0.1:8004"}},
    ]
    assert public_origin(tunnels, "http://127.0.0.1:8004") == "https://demo.example"
    assert public_origin(tunnels, "http://127.0.0.1:9999") is None


def test_controller_lock_releases_even_when_its_file_remains(monkeypatch):
    path = ngrok.ROOT / "runtime" / ("ngrok-lock-test-" + secrets.token_hex(8))
    monkeypatch.setattr(ngrok, "LOCK", path)
    try:
        lock = ngrok.acquire_lock()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                ngrok.acquire_lock()
        finally:
            lock.close()
        assert ngrok.LOCK.exists()
        ngrok.acquire_lock().close()
    finally:
        path.unlink(missing_ok=True)
