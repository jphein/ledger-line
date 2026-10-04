"""Owns the HTTP transport: ThreadingHTTPServer on 0.0.0.0:$PORT (R-03, S-01)."""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from .app import Request, dispatch
from .jsonio import encode
from .state import Store

MAX_BODY = 8 * 1024 * 1024


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pocketful"
    store = None  # set by make_server

    def _handle(self):
        split = urlsplit(self.path)
        query = {}
        for name, value in parse_qsl(split.query, keep_blank_values=True):
            query.setdefault(name, value)
        length = self.headers.get("Content-Length")
        try:
            length = int(length) if length else 0
        except ValueError:
            length = 0
        if length < 0 or length > MAX_BODY:
            status, body = 400, {"error": {"code": "malformed_request",
                                           "message": "bad Content-Length"}}
            self.close_connection = True
        else:
            raw = self.rfile.read(length) if length else b""
            req = Request(self.command, unquote(split.path), query, self.headers, raw)
            status, body = dispatch(self.store, req)
        self._send(status, body)

    def _send(self, status, body):
        self.send_response(status)
        if body is None:
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = encode(body)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

    def send_error(self, code, message=None, explain=None):
        """Transport-level errors also get the JSON error body (R-21, D-09)."""
        if code == 501:  # unsupported method: treated like any unknown route
            code, error = 404, "not_found"
        else:
            error = "not_found" if code == 404 else "malformed_request"
        self.close_connection = True
        self._send(code, {"error": {"code": error, "message": message or error}})

    def log_message(self, format, *args):
        pass


def make_server(port, store=None):
    handler = type("BoundHandler", (Handler,), {"store": store or Store()})
    return Server(("0.0.0.0", port), handler)


def main():
    port = int(os.environ.get("PORT") or 8080)
    make_server(port).serve_forever()


if __name__ == "__main__":
    main()
