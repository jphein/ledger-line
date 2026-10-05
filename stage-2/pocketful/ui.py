"""Owns the browser UI transport: content negotiation and static assets (D-200, D-201).

A GET whose Accept header contains text/html on a screen route gets the HTML
shell; everything else keeps the JSON API behaviour, so `/requests` and
`/authorizations` serve both (R-236, S-201). Assets live in pocketful/static and
ship inside the image (R-201).
"""
import os

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

SCREENS = {
    "/": ("wallet", "Wallet"),
    "/requests": ("requests", "Requests"),
    "/split": ("split", "Split a bill"),
    "/authorizations": ("authorizations", "Holds"),
    "/signup": ("signup", "Create your account"),
    "/login": ("login", "Sign in"),
}

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".html": "text/html; charset=utf-8",
}


class Raw:
    """A non-JSON response body with its content type."""

    def __init__(self, content_type, data):
        self.content_type = content_type
        self.data = data


def _read(name):
    with open(os.path.join(STATIC_DIR, name), "rb") as f:
        return f.read()


_SHELL = _read("shell.html").decode("utf-8")
_ASSETS = {name: _read(name) for name in os.listdir(STATIC_DIR)
           if os.path.splitext(name)[1] in CONTENT_TYPES and name != "shell.html"}


def wants_html(headers):
    return "text/html" in (headers.get("Accept") or "").lower()


def serve(req):
    """Return (status, Raw) for a UI request, or None to fall through to the API."""
    if req.method != "GET":
        return None
    if req.path.startswith("/static/"):
        name = req.path[len("/static/"):]
        if name in _ASSETS:
            return 200, Raw(CONTENT_TYPES[os.path.splitext(name)[1]], _ASSETS[name])
        return None
    screen = SCREENS.get(req.path)
    if screen is None or not wants_html(req.headers):
        return None
    html = _SHELL.replace("{{screen}}", screen[0]).replace("{{title}}", screen[1])
    return 200, Raw(CONTENT_TYPES[".html"], html.encode("utf-8"))
