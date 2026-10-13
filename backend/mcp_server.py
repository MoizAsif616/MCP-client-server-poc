from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ListToolsResult, TextContent
from urllib.parse import urlsplit

from backend.authentication import principal
from backend.logging import log_tool
from backend.permissions import authorize, own_user, permitted_tools
from backend.tools import TOOLS


def build_mcp(settings):
    async def permissions(ctx, call_next):
        identity = None
        name = (ctx.params or {}).get("name", "<missing>")
        is_call = ctx.method == "tools/call"
        try:
            if ctx.method in {"tools/list", "tools/call"}:
                identity = principal(ctx.request)
            if is_call:
                authorize(identity["user"], name)
                if name in {"list_notes", "get_profile"}:
                    own_user(identity["user"], ((ctx.params or {}).get("arguments") or {}).get("user_id"))
            result = await call_next(ctx)
            if ctx.method == "tools/list":
                allowed = permitted_tools(identity["user"])
                result = ListToolsResult.model_validate(result)
                result.tools = [tool for tool in result.tools if tool.name in allowed]
            if is_call:
                parsed = CallToolResult.model_validate(result)
                log_tool(settings, name, identity, "tool_error" if parsed.is_error else "success")
            return result
        except PermissionError as exc:
            if is_call:
                log_tool(settings, name, identity, "denied: " + str(exc))
            return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)
        except Exception as exc:
            if is_call:
                log_tool(settings, name, identity, "error: " + str(exc))
            raise

    mcp = MCPServer(settings.name, version="1.0.0", middleware=[permissions], subscriptions=False)
    for tool in TOOLS:
        mcp.add_tool(tool)
    host = urlsplit(settings.public_url).netloc
    origins = [settings.public_url, "http://127.0.0.1:*", "http://localhost:*"]
    security = TransportSecuritySettings(allowed_hosts=[host, "127.0.0.1:*", "localhost:*"],
                                         allowed_origins=origins)
    app = mcp.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
    return mcp, app
