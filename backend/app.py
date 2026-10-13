from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from backend import oauth, web
from backend.authentication import ProtectMCP
from backend.config import ROOT, Settings
from backend.logging import HTTPLogMiddleware
from backend.mcp_server import build_mcp
from backend.storage import Store


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings)
    mcp, mcp_app = build_mcp(settings)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=web.routes + oauth.routes + [
        Mount("/static", StaticFiles(directory=ROOT / "backend" / "static")),
        Mount("/", app=mcp_app),
    ], lifespan=lifespan, exception_handlers={oauth.OAuthError: oauth.oauth_error}, middleware=[
        Middleware(ProtectMCP, settings=settings, store=store),
    ])
    for target in (app, mcp_app):
        target.state.settings = settings
        target.state.store = store
        target.state.mcp = mcp
        target.state.templates = Jinja2Templates(directory=ROOT / "backend" / "templates")
    return HTTPLogMiddleware(app, path=settings.log_dir / "http.jsonl")
