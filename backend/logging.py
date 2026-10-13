import base64
import json
import threading
from datetime import datetime, timezone
from pathlib import Path


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


class HTTPLogMiddleware:
    def __init__(self, app, path):
        self.app, self.path = app, path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope["headers"]
        host = next((v.decode("latin-1") for k, v in headers if k.lower() == b"host"), "")
        raw_path = scope.get("raw_path", scope["path"].encode()).decode("ascii")
        query = scope.get("query_string", b"").decode("ascii")
        url = f'{scope["scheme"]}://{host}{raw_path}' + ("?" + query if query else "")
        request_body, response_body = bytearray(), bytearray()
        status, response_headers = None, []
        request_logged, response_logged = False, False

        def log_request():
            nonlocal request_logged
            if not request_logged:
                record_http(self.path, "received_request", scope["method"], url, headers, bytes(request_body))
                request_logged = True

        async def logged_receive():
            message = await receive()
            if message["type"] == "http.request":
                request_body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    log_request()
            return message

        async def logged_send(message):
            nonlocal status, response_headers, response_logged
            if message["type"] == "http.response.start":
                status, response_headers = message["status"], message["headers"]
            if message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    record_http(self.path, "sent_response", scope["method"], url,
                                response_headers, bytes(response_body), status)
                    response_logged = True
            await send(message)

        # Drain once and replay so even rejected requests retain their exact bodies.
        messages = []
        while True:
            message = await logged_receive()
            messages.append(message)
            if message["type"] != "http.request" or not message.get("more_body", False):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()

        try:
            await self.app(scope, replay, logged_send)
        finally:
            log_request()
            if status is not None and not response_logged:
                record_http(self.path, "sent_response", scope["method"], url,
                            response_headers, bytes(response_body), status)


def log_tool(settings, name, identity, outcome):
    append(settings.log_dir / "tools.jsonl", {
        "timestamp": timestamp(), "tool_name": name,
        "originating_client": identity["token"]["client_id"] if identity else None,
        "receiving_server": settings.resource,
        "authenticated_user": identity["user"]["email"] if identity else None,
        "outcome": outcome,
    })
