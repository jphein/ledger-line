"""Test helpers: a sample fixture and a JSON-in/JSON-out client over `dispatch`."""
import json
import unittest

from pocketful.app import Request, dispatch
from pocketful.state import Store


def fixture():
    return {
        "currency": "EUR", "minor_units": 2,
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
             "display_name": "Ada", "handle": "ada", "balance": 10000},
            {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
             "display_name": "Bob", "handle": "bob", "balance": 2500},
            {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
             "display_name": "Cy", "handle": "cy", "balance": 0},
        ],
        "payments": [
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 500, "note": "coffee", "visibility": "public"},
        ],
        "requests": [
            {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
             "amount": 1200, "note": "taxi", "status": "pending"},
        ],
        "settlement_operator_ids": ["u_cy"],
    }


class ServiceCase(unittest.TestCase):
    """Starts each test from a freshly reset store with tokens for ada, bob and cy."""

    def setUp(self):
        self.store = Store()
        status, _ = self.call("POST", "/_test/reset", fixture())
        self.assertEqual(status, 204)
        self.tok = {h: self.login(f"{h}@example.com") for h in ("ada", "bob", "cy")}

    def call(self, method, path, body=None, token=None, key=None, raw=None, query=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if key is not None:
            headers["Idempotency-Key"] = key
        if raw is None:
            raw = b"" if body is None else json.dumps(body).encode()
        return dispatch(self.store, Request(method, path, query or {}, headers, raw))

    def login(self, email, password="correct horse"):
        status, body = self.call("POST", "/auth/login", {"email": email, "password": password})
        self.assertEqual(status, 200, body)
        return body["token"]

    def balance(self, who):
        status, body = self.call("GET", "/me", token=self.tok[who])
        self.assertEqual(status, 200, body)
        return body["balance"]

    def assertError(self, result, status, code):
        self.assertEqual(result[0], status, result[1])
        self.assertEqual(result[1]["error"]["code"], code, result[1])
