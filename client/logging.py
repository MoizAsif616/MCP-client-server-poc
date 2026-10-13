import base64
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx2

_lock = threading.Lock()


def append(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def body_value(body):
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(body).decode("ascii")}


def record_http(path, direction, method, url, headers, body, status=None):
    pairs = [(key.decode("latin-1"), value.decode("latin-1")) for key, value in headers]
    row = {"timestamp": timestamp(), "direction": direction, "method": method, "url": url,
           "headers": pairs, "content_type": next((v for k, v in pairs if k.lower() == "content-type"), None),
           "body": body_value(body)}
    if status is not None:
        row["status"] = status
    append(path, row)


class RecordingStream(httpx2.AsyncByteStream):
    def __init__(self, stream, finish):
        self.stream, self.finish = stream, finish
        self.body = bytearray()
        self.finished = False

    def flush(self):
        if not self.finished:
            self.finish(bytes(self.body))
            self.finished = True

    async def __aiter__(self):
        try:
            async for chunk in self.stream:
                self.body.extend(chunk)
                yield chunk
        finally:
            self.flush()

    async def aclose(self):
        self.flush()
        await self.stream.aclose()


class RecordingTransport(httpx2.AsyncBaseTransport):
    def __init__(self, path):
        self.path = path
        self.transport = httpx2.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        body = await request.aread()
        record_http(self.path, "sent_request", request.method, str(request.url), request.headers.raw, body)
        response = await self.transport.handle_async_request(request)
        response.stream = RecordingStream(response.stream, lambda data: record_http(
            self.path, "received_response", request.method, str(request.url),
            response.headers.raw, data, response.status_code))
        return response

    async def aclose(self):
        await self.transport.aclose()
