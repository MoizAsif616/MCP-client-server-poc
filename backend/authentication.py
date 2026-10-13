import secrets
import time
import json

from starlette.responses import JSONResponse


def browser_session(request):
    return request.app.state.store.session(request.cookies.get("session", ""))


def browser_user(request):
    session = browser_session(request)
    return request.app.state.store.user(session["user_id"]) if session and session["user_id"] else None


def check_csrf(request, form):
    session = browser_session(request)
    if not session or not secrets.compare_digest(str(form.get("csrf", "")), session["csrf"]):
        raise PermissionError("Invalid form token; reload the page")


def principal(request):
    settings = request.app.state.settings
    store = request.app.state.store
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise PermissionError("Missing bearer token")
    token = store.access(value)
    if not token or token["access_expires"] <= time.time():
        raise PermissionError("Invalid or expired bearer token")
    if token["resource"] != settings.resource:
        raise PermissionError("Token is for a different resource")
    if "tools" not in token["scope"].split():
        raise PermissionError("insufficient_scope")
    user = store.user(token["user_id"])
    if not user:
        raise PermissionError("Unknown user")
    return {"user": user, "token": token}


class ProtectMCP:
    def __init__(self, app, settings, store):
        self.app, self.settings, self.store = app, settings, store

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].rstrip("/") == "/mcp" and scope["method"] != "OPTIONS":
            from starlette.requests import Request
            request = Request(scope, receive=receive)
            try:
                principal(request)
            except PermissionError as exc:
                from backend.logging import log_tool
                try:
                    payload = json.loads(await request.body())
                    if isinstance(payload, dict) and payload.get("method") == "tools/call":
                        log_tool(self.settings, payload.get("params", {}).get("name", "<missing>"),
                                 None, "denied: " + str(exc))
                except (ValueError, AttributeError):
                    pass
                insufficient = str(exc) == "insufficient_scope"
                error = "insufficient_scope" if insufficient else "invalid_token"
                challenge = (f'Bearer resource_metadata="{self.settings.metadata_url}", '
                             f'scope="tools", error="{error}"')
                response = JSONResponse({"error": error, "error_description": str(exc)},
                                        status_code=403 if insufficient else 401,
                                        headers={"WWW-Authenticate": challenge})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
