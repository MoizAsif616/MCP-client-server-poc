import asyncio
import queue
import socket
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from mcp.client.auth import AuthorizationCodeResult
from mcp.client.auth import OAuthClientProvider

from client.logging import record_http


class StoredOAuthProvider(OAuthClientProvider):
    async def _initialize(self):
        await super()._initialize()
        # SDK 2.3.0 loads stored tokens without restoring their expiry clock.
        if self.context.current_tokens:
            self.context.update_token_expiry(self.context.current_tokens)


class CallbackHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class CallbackListener:
    def __init__(self, config, timeout=180):
        self.config, self.timeout = config, timeout
        self.expected_state = None
        self.result = queue.Queue()
        self.server = None

    def __enter__(self):
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def __getattr__(self, name):
                if name.startswith("do_"):
                    return self.do_GET
                raise AttributeError(name)

            def do_GET(self):
                url = "http://" + self.headers.get("Host", "") + self.path
                headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in self.headers.raw_items()]
                log_path = listener.config.log_dir / "callback-http.jsonl"
                request_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                record_http(log_path, "received_request", self.command, url, headers, request_body)
                query = parse_qs(urlsplit(self.path).query)
                state = query.get("state", [""])[0]
                valid = (self.command == "GET" and urlsplit(self.path).path == urlsplit(listener.config.callback_url).path
                         and listener.expected_state is not None
                         and secrets.compare_digest(state, listener.expected_state)
                         and all(len(values) == 1 for values in query.values()))
                status = 200 if valid else (400 if self.command == "GET" else 405)
                body = b"Authorization received. You may return to the client." if valid else b"Invalid callback path or state."
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                response_headers = [tuple(line.rstrip(b"\r\n").split(b": ", 1)) for line in self._headers_buffer[1:]]
                self.end_headers()
                response_body = b"" if self.command == "HEAD" else body
                self.wfile.write(response_body)
                record_http(log_path, "sent_response", self.command, url, response_headers, response_body, status)
                if valid:
                    listener.result.put(query)

        self.server = CallbackHTTPServer(("127.0.0.1", self.config.callback_port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    async def redirect(self, url):
        self.expected_state = parse_qs(urlsplit(url).query)["state"][0]
        print(f"\nAuthorize {self.config.name} in your browser:\n{url}", flush=True)
        await asyncio.to_thread(webbrowser.open, url)

    async def callback(self):
        try:
            query = await asyncio.to_thread(self.result.get, True, self.timeout)
        except queue.Empty:
            raise RuntimeError("Authorization timed out. Run the client again and finish browser consent.")
        if "error" in query:
            raise RuntimeError("Authorization denied: " + query["error"][0])
        if "code" not in query:
            raise RuntimeError("Authorization callback has no code")
        return AuthorizationCodeResult(code=query["code"][0], state=query["state"][0],
                                       iss=query.get("iss", [None])[0])
