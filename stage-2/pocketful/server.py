"""Owns the HTTP transport: ThreadingHTTPServer on 0.0.0.0:$PORT (R-03, S-01)."""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from .app import Request, dispatch
from .jsonio import encode
from .state import Store
from .ui import Raw

MAX_BODY = 8 * 1024 * 1024


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pocketful"
    timeout = 10  # a stalled client cannot pin a worker thread forever
    store = None  # set by make_server

    def _handle(self):
        split = urlsplit(self.path)
        query = {}
        for name, value in parse_qsl(split.query, keep_blank_values=True):
            query.setdefault(name, value)
        try:
            raw = self._read_body()
        except ValueError as err:
            self.close_connection = True
            self._send(400, {"error": {"code": "malformed_request", "message": str(err)}})
            return
        req = Request(self.command, unquote(split.path), query, self.headers, raw)
        self._send(*dispatch(self.store, req))

    def _read_body(self):
        """Read a Content-Length or chunked body; ValueError when it cannot be framed."""
        encoding = (self.headers.get("Transfer-Encoding") or "").strip().lower()
        if encoding == "chunked":
            return self._read_chunked()
        if encoding and encoding != "identity":
            raise ValueError("unsupported Transfer-Encoding")
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        if not length.strip().isdigit() or int(length) > MAX_BODY:
            raise ValueError("bad Content-Length")
        raw = self.rfile.read(int(length))
        if len(raw) != int(length):
            raise ValueError("body shorter than Content-Length")
        return raw

    def _read_chunked(self):
        body = bytearray()
        while True:
            size_line = self.rfile.readline(1024).split(b";", 1)[0].strip()
            try:
                size = int(size_line, 16)
            except ValueError:
                raise ValueError("bad chunk size")
            if size < 0 or len(body) + size > MAX_BODY:
                raise ValueError("chunked body too large")
            if size == 0:
                while self.rfile.readline(1024).strip():  # trailers
                    pass
                return bytes(body)
            chunk = self.rfile.read(size)
            if len(chunk) != size or self.rfile.read(2) != b"\r\n":
                raise ValueError("truncated chunk")
            body += chunk

    def _send(self, status, body):
        self.send_response(status)
        if body is None:
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if isinstance(body, Raw):
            payload, content_type = body.data, body.content_type
            self.send_header("Cache-Control", "no-cache")
        else:
            payload, content_type = encode(body), "application/json; charset=utf-8"
        self.send_header("Content-Type", content_type)
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
