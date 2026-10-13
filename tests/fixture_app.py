import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route

from backend.logging import HTTPLogMiddleware


async def health(request):
    return PlainTextResponse("ready")


async def crash(request):
    raise ValueError("Deliberate logging verification error")


async def stream(request):
    async def chunks():
        yield b'event: message\ndata: {"value":2}\n\n'
        yield b'event: message\ndata: {"value":true}\n\n'
    return StreamingResponse(chunks(), media_type="text/event-stream")


app = HTTPLogMiddleware(Starlette(routes=[Route("/health", health), Route("/crash", crash), Route("/stream", stream)]),
                        path=Path(os.environ["FIXTURE_LOG"]))
