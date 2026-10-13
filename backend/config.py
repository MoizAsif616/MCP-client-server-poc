import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Settings:
    name: str = os.getenv("SERVER_NAME", "Learning MCP")
    port: int = int(os.getenv("PORT", "8000"))
    public_url: str = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
    database: Path = Path(os.getenv("DATABASE", str(ROOT / "data" / "app.sqlite3")))
    log_dir: Path = Path(os.getenv("LOG_DIR", str(ROOT / "logs" / "backend")))
    access_seconds: int = int(os.getenv("ACCESS_TOKEN_SECONDS", "3600"))
    refresh_seconds: int = int(os.getenv("REFRESH_TOKEN_SECONDS", "604800"))
    session_seconds: int = 86400
    code_seconds: int = 120

    @property
    def resource(self):
        return self.public_url + "/mcp"

    @property
    def metadata_url(self):
        return self.public_url + "/.well-known/oauth-protected-resource/mcp"

    @property
    def secure_cookies(self):
        return urlsplit(self.public_url).scheme == "https"

    def __post_init__(self):
        parsed = urlsplit(self.public_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
            raise ValueError("PUBLIC_URL must be an origin, such as https://example.com")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Use HTTPS except for loopback development")
        if self.access_seconds < 1 or self.refresh_seconds < 1:
            raise ValueError("Token lifetimes must be positive")
