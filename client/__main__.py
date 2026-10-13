import argparse
import asyncio
import json
import sys

from client.config import ROOT, load_servers
from client.errors import error_text
from client.routing import ToolRouter


def show_result(result):
    if result.is_error:
        print("Tool error:")
    if result.structured_content is not None:
        print(json.dumps(result.structured_content, indent=2, ensure_ascii=False))
    else:
        for item in result.content:
            print(getattr(item, "text", str(item)))


async def run(args):
    router = ToolRouter(load_servers(args.config))
    if args.command == "call":
        arguments = json.loads(args.args)
        if not isinstance(arguments, dict):
            raise ValueError("Arguments must be a JSON object")
        result = await router.call(args.tool, arguments)
        show_result(result)
        return 2 if result.is_error else 0
    tools = await router.discover()
    for name, entry in tools.items():
        tool = entry["tool"]
        print(f"\n{name} — {tool.description}\nArguments: {json.dumps(tool.input_schema)}")
    for server, error in router.errors.items():
        print(f"\n{server}: connection failed: {error}")
    if args.command == "interactive" and tools:
        while True:
            name = (await asyncio.to_thread(input, "\nTool name (or quit): ")).strip()
            if name == "quit":
                break
            try:
                if name not in tools:
                    raise ValueError("Choose one of the listed server:tool names")
                raw = await asyncio.to_thread(input, "Arguments as JSON ({} for none): ")
                show_result(await router.call(name, json.loads(raw)))
            except Exception as exc:
                print("Error:", error_text(exc))
    if router.errors and not tools:
        raise RuntimeError("No configured server could be reached")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Independent MCP client; no LLM or paid API needed.")
    parser.add_argument("--config", default=str(ROOT / "client" / "servers.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("interactive")
    call = commands.add_parser("call")
    call.add_argument("tool", help="server:tool")
    call.add_argument("--args", default="{}", help="JSON argument object")
    args = parser.parse_args()
    try:
        parser.exit(asyncio.run(run(args)) or 0)
    except KeyboardInterrupt:
        print("\nClient stopped.")
    except Exception as exc:
        parser.exit(1, f"Error: {error_text(exc)}\n")


if __name__ == "__main__":
    main()
