import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ServerConfig:
    name: str
    url: str
    callback_url: str = "http://127.0.0.1:8765/callback"
    callback_port: int = 8765
    token_dir: Path = ROOT / "client" / "tokens"
    log_dir: Path = ROOT / "logs" / "client"

    def __post_init__(self):
        if not self.name or not self.name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Server names must contain letters, numbers, underscores or hyphens")
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.fragment or parsed.query:
            raise ValueError("Use an HTTP(S) MCP URL without query or fragment")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Use HTTPS except on loopback")
        self.token_dir, self.log_dir = Path(self.token_dir), Path(self.log_dir)


def load_servers(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    result = [ServerConfig(**entry) for entry in data["servers"]]
    if not result or len({s.name for s in result}) != len(result):
        raise ValueError("Configure at least one server, with unique names")
    return result
