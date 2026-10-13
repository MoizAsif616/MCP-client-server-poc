from client.connection import connect
from client.errors import error_text


class ToolRouter:
    def __init__(self, servers, browser_handler=None):
        self.servers = {server.name: server for server in servers}
        self.browser_handler = browser_handler
        self.tools = {}
        self.errors = {}

    async def discover(self):
        self.tools, self.errors = {}, {}
        for name, config in self.servers.items():
            try:
                async with connect(config, self.browser_handler) as sdk:
                    cursor = None
                    while True:
                        page = await sdk.list_tools(cursor=cursor)
                        for tool in page.tools:
                            self.tools[f"{name}:{tool.name}"] = {"server": config, "tool": tool}
                        cursor = page.next_cursor
                        if not cursor:
                            break
            except Exception as exc:
                self.errors[name] = error_text(exc)
        return self.tools

    async def call(self, qualified_name, arguments):
        prefix, separator, name = qualified_name.partition(":")
        if not separator or prefix not in self.servers or not name:
            raise ValueError("Use server:tool, for example local:add")
        config = self.servers[prefix]
        async with connect(config, self.browser_handler) as sdk:
            return await sdk.call_tool(name, arguments)
