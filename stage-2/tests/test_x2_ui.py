"""X2: HTML content negotiation and static assets (R-201, R-235, R-236, S-200, S-201, D-201)."""
import json
import threading
import unittest
import urllib.error
import urllib.request

from pocketful.server import make_server
from pocketful.ui import Raw
from tests.helpers import ServiceCase

BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class NegotiationTests(ServiceCase):
    def get(self, path, accept=None, token=None):
        headers = {"Accept": accept} if accept else {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        from pocketful.app import Request, dispatch
        return dispatch(self.store, Request("GET", path, {}, headers, b""))

    def test_screens_serve_html_for_browser_accept(self):
        for path, screen in (("/", "wallet"), ("/requests", "requests"), ("/split", "split"),
                             ("/signup", "signup"), ("/login", "login"),
                             ("/authorizations", "authorizations")):
            status, body = self.get(path, BROWSER_ACCEPT)
            self.assertEqual(status, 200, path)
            self.assertIsInstance(body, Raw)
            self.assertEqual(body.content_type, "text/html; charset=utf-8")
            self.assertIn(f'data-screen="{screen}"'.encode(), body.data)
            self.assertNotIn(b"http://", body.data)
            self.assertNotIn(b"https://", body.data)

    def test_api_paths_keep_json_without_html_accept(self):
        status, body = self.get("/requests", "application/json", token=self.tok["ada"])
        self.assertEqual((status, set(body)), (200, {"requests", "has_more"}))
        status, body = self.get("/authorizations", None, token=self.tok["ada"])
        self.assertEqual((status, set(body)), (200, {"authorizations", "has_more"}))
        self.assertError(self.get("/requests"), 401, "unauthenticated")
        for path in ("/", "/split", "/signup", "/login"):
            self.assertError(self.get(path, "application/json"), 404, "not_found")

    def test_static_assets_are_local(self):
        for name, kind in (("app.js", "text/javascript"), ("app.css", "text/css"),
                           ("logo.svg", "image/svg+xml")):
            status, body = self.get(f"/static/{name}")
            self.assertEqual(status, 200)
            self.assertTrue(body.content_type.startswith(kind))
            self.assertNotIn(b"https://", body.data)  # no CDN or remote fonts (R-201)
        self.assertError(self.get("/static/../server.py"), 404, "not_found")
        self.assertError(self.get("/static/shell.html"), 404, "not_found")

    def test_ui_money_code_avoids_locale_formatting_and_floats(self):
        js = self.get("/static/app.js")[1].data.decode()
        for forbidden in ("toLocaleString", "NumberFormat", "parseFloat", "toFixed"):
            self.assertNotIn(forbidden, js)
        self.assertIn('"Accept": "application/json"', js)


class HttpHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_html_over_http(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/requests",
                                     headers={"Accept": BROWSER_ACCEPT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.headers["Content-Type"], "text/html; charset=utf-8")
            self.assertIn(b"<!doctype html>", resp.read())
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/requests")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(json.loads(ctx.exception.read())["error"]["code"], "unauthenticated")
