import uvicorn

from backend.app import create_app
from backend.config import Settings

if __name__ == "__main__":
    settings = Settings()
    print(f"Website: {settings.public_url} | MCP: {settings.resource}")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, access_log=False,
                proxy_headers=True, forwarded_allow_ips="127.0.0.1", server_header=False, date_header=False)
