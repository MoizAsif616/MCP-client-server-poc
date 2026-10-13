import hashlib
import json
import time

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class FileTokenStorage:
    def __init__(self, config):
        key = hashlib.sha256(config.url.encode()).hexdigest()[:16]
        self.path = config.token_dir / f"{config.name}-{key}.json"

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp.replace(self.path)

    async def get_tokens(self):
        data = self.read()
        if "tokens" not in data:
            return None
        tokens = dict(data["tokens"])
        if data.get("expires_at"):
            tokens["expires_in"] = max(0, int(data["expires_at"] - time.time()))
        return OAuthToken.model_validate(tokens)

    async def set_tokens(self, tokens):
        data = self.read()
        data["tokens"] = tokens.model_dump(mode="json")
        data["expires_at"] = time.time() + tokens.expires_in if tokens.expires_in is not None else None
        self.write(data)

    async def get_client_info(self):
        data = self.read()
        info = data.get("client_info")
        return OAuthClientInformationFull.model_validate(info) if info else None

    async def set_client_info(self, info):
        data = self.read()
        data["client_info"] = info.model_dump(mode="json")
        self.write(data)
