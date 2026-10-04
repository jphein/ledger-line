"""Shared helpers for the prover's black-box suite.

Everything here talks to the service over HTTP only. Nothing is derived from product code.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx

BASE = os.environ.get("POCKETFUL_URL", "http://127.0.0.1:18080").rstrip("/")
BUDGET_S = 5.0          # R-05 per-request budget
RESET_BUDGET_S = 10.0   # R-05 / §10 test-control budget
PW = "correct horse"
CT_JSON = "application/json; charset=utf-8"

RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

# Global convention violations, keyed by ledger line. Reported by conftest's summary.
VIOLATIONS: dict[str, list[str]] = {}
_vlock = threading.Lock()


def violation(line: str, detail: str) -> None:
    with _vlock:
        VIOLATIONS.setdefault(line, [])
        if len(VIOLATIONS[line]) < 20:
            VIOLATIONS[line].append(detail)


_NOTSET = object()
_shared = httpx.Client(timeout=30.0, limits=httpx.Limits(max_connections=100,
                                                        max_keepalive_connections=100,
                                                        keepalive_expiry=5.0))


def new_key() -> str:
    return uuid.uuid4().hex


def _check_conventions(method, path, resp, elapsed, budget):
    where = f"{method} {path} -> {resp.status_code}"
    if resp.status_code >= 500:
        violation("R-30", f"{where} body={resp.text[:200]!r}")
        violation("I-08", f"5xx: {where}")
    if elapsed >= budget:
        violation("R-05", f"{where} took {elapsed:.2f}s (budget {budget}s)")
        violation("I-08", f"slow: {where} {elapsed:.2f}s")
    if resp.status_code == 204:
        if resp.content:
            violation("S-16", f"{where} 204 carried a body {resp.content[:80]!r}")
        return
    ct = resp.headers.get("content-type", "")
    if ct.replace(" ", "").lower() != CT_JSON.replace(" ", ""):
        violation("R-07", f"{where} content-type={ct!r}")
        violation("S-16", f"{where} content-type={ct!r}")
    try:
        body = resp.json()
    except Exception:
        violation("R-07", f"{where} body not JSON: {resp.content[:120]!r}")
        return
    if resp.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        if not (isinstance(err, dict) and isinstance(err.get("code"), str)
                and isinstance(err.get("message"), str)):
            violation("R-21", f"{where} error body={body!r:.200}")


class Api:
    """One caller. `token=None` sends no Authorization header."""

    def __init__(self, token: str | None = None, *, user_id=None, handle=None,
                 client: httpx.Client | None = None):
        self.token = token
        self.user_id = user_id
        self.handle = handle
        self.http = client or _shared

    def request(self, method, path, json=_NOTSET, *, raw=None, key=None, headers=None,
                budget=None, content_type=True):
        h = {}
        if self.token is not None:
            h["Authorization"] = f"Bearer {self.token}"
        if key is not None:
            h["Idempotency-Key"] = key
        content = None
        if raw is not None:
            content = raw if isinstance(raw, bytes) else raw.encode()
        elif json is not _NOTSET:
            content = _json_dumps(json).encode()
        if content is not None and content_type:
            h["Content-Type"] = CT_JSON
        if headers:
            h.update(headers)
        budget = budget or (RESET_BUDGET_S if path.startswith("/_test/") else BUDGET_S)
        t0 = time.monotonic()
        resp = self.http.request(method, BASE + path, content=content, headers=h)
        elapsed = time.monotonic() - t0
        _check_conventions(method, path, resp, elapsed, budget)
        assert resp.status_code < 500, f"5xx from {method} {path}: {resp.text[:300]}"
        return resp

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, json=_NOTSET, **kw):
        return self.request("POST", path, json, **kw)

    # conveniences
    def me(self) -> dict:
        r = self.get("/me")
        assert r.status_code == 200, r.text
        return r.json()

    def balance(self) -> int:
        return self.me()["balance"]

    def pay(self, to_handle, amount, key=None, **extra):
        body = {"to_handle": to_handle, "amount": amount, **extra}
        return self.post("/payments", body, key=key or new_key())

    def ask(self, payer_handle, amount, key=None, **extra):
        body = {"payer_handle": payer_handle, "amount": amount, **extra}
        return self.post("/requests", body, key=key or new_key())

    def pay_request(self, rid, body=None, key=None):
        return self.post(f"/requests/{rid}/pay", {} if body is None else body,
                         key=key or new_key())

    def activity(self) -> list[dict]:
        return _all_pages(self, "/activity", "payments")

    def requests(self, query: str = "") -> list[dict]:
        return _all_pages(self, "/requests" + (f"?{query}" if query else ""), "requests")


def _json_dumps(v):
    return json.dumps(v, ensure_ascii=False)


def _all_pages(api: Api, path: str, field: str) -> list[dict]:
    out, offset = [], 0
    sep = "&" if "?" in path else "?"
    while True:
        r = api.get(f"{path}{sep}limit=200&offset={offset}")
        assert r.status_code == 200, r.text
        body = r.json()
        out.extend(body[field])
        if not body["has_more"]:
            return out
        offset += 200
        assert offset < 100000, "runaway pagination"


# ---------------------------------------------------------------- errors / shapes

def err(resp, status: int, code: str | None = None):
    assert resp.status_code == status, (
        f"expected {status} {code}, got {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    assert isinstance(body, dict) and isinstance(body.get("error"), dict), body
    if code is not None:
        assert body["error"].get("code") == code, (
            f"expected code {code}, got {body['error'].get('code')!r}")
    assert isinstance(body["error"].get("message"), str), body
    return body


def ok(resp, status: int = 200):
    assert resp.status_code == status, (
        f"expected {status}, got {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else None


def check_id(v, what="id"):
    if not (isinstance(v, str) and 1 <= len(v) <= 64):
        violation("R-10", f"{what}={v!r}")
    assert isinstance(v, str), f"{what} must be a string, got {v!r}"


def check_ts(v, what="timestamp"):
    if not (isinstance(v, str) and RFC3339.match(v)):
        violation("R-08", f"{what}={v!r}")
    assert isinstance(v, str), f"{what} must be a string"


PAYMENT_KEYS = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                "amount", "currency", "note", "visibility", "request_id", "settlement_id",
                "created_at"}
REQUEST_KEYS = {"request_id", "requester_id", "requester_handle", "payer_id",
                "payer_handle", "amount", "currency", "note", "status", "payment_id",
                "created_at"}


def check_payment(p: dict, **expect):
    missing = PAYMENT_KEYS - set(p)
    assert not missing, f"payment missing fields {missing}: {p}"
    check_id(p["payment_id"], "payment_id")
    check_ts(p["created_at"], "payment.created_at")
    assert type(p["amount"]) is int, f"amount must be a JSON integer: {p['amount']!r}"
    assert isinstance(p["note"], str)
    assert p["visibility"] in ("public", "private")
    for k, v in expect.items():
        assert p[k] == v, f"payment.{k}: expected {v!r}, got {p[k]!r}"
    return p


def check_request(q: dict, **expect):
    missing = REQUEST_KEYS - set(q)
    assert not missing, f"request missing fields {missing}: {q}"
    check_id(q["request_id"], "request_id")
    check_ts(q["created_at"], "request.created_at")
    assert type(q["amount"]) is int, f"amount must be a JSON integer: {q['amount']!r}"
    assert q["status"] in ("pending", "paid", "declined", "cancelled")
    for k, v in expect.items():
        assert q[k] == v, f"request.{k}: expected {v!r}, got {q[k]!r}"
    return q


# ---------------------------------------------------------------- fixtures

def user(uid, handle, balance, email=None, name=None, password=PW):
    return {"id": uid, "email": email or f"{handle}@example.com", "password": password,
            "display_name": name or handle.title(), "handle": handle, "balance": balance}


ADA = user("u_ada", "ada", 10000)
BOB = user("u_bob", "bob", 2500)
CY = user("u_cy", "cy", 500)
DEE = user("u_dee", "dee", 0)
EVE = user("u_eve", "eve", 0)
FAY = user("u_fay", "fay", 0)
OP = user("u_op", "op", 0)

SEED_PAYMENTS = [
    {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
     "note": "coffee", "visibility": "public"},
    {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100,
     "note": "secret gift", "visibility": "private"},
]
SEED_REQUESTS = [
    {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
     "note": "taxi", "status": "pending"},
    {"id": "rq_2", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 300,
     "note": "lunch", "status": "declined"},
]


def fixture(users=None, payments=None, requests=None, operators=None,
            currency="EUR", minor_units=2):
    f = {"currency": currency, "minor_units": minor_units,
         "users": copy.deepcopy(users if users is not None else [ADA, BOB, CY, DEE]),
         "payments": copy.deepcopy(payments if payments is not None else SEED_PAYMENTS),
         "requests": copy.deepcopy(requests if requests is not None else SEED_REQUESTS)}
    if operators is not None:
        f["settlement_operator_ids"] = list(operators)
    return f


def reset(fix: dict):
    r = Api().post("/_test/reset", fix)
    assert r.status_code == 204, f"reset failed: {r.status_code} {r.text[:300]}"
    return r


def login(email, password=PW) -> Api:
    r = Api().post("/auth/login", {"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    b = r.json()
    return Api(b["token"], user_id=b["user_id"])


def world(fix: dict | None = None) -> SimpleNamespace:
    """Reset to `fix` and log every seeded user in. Attribute per handle."""
    fix = fix or fixture()
    reset(fix)
    with ThreadPoolExecutor(8) as ex:
        apis = list(ex.map(lambda u: login(u["email"], u["password"]), fix["users"]))
    ns = SimpleNamespace(fixture=fix, total=sum(u["balance"] for u in fix["users"]),
                         users={})
    for u, a in zip(fix["users"], apis):
        a.handle = u["handle"]
        setattr(ns, u["handle"], a)
        ns.users[u["handle"]] = a
    return ns


def total_balance(w) -> int:
    return sum(a.balance() for a in w.users.values())


# ---------------------------------------------------------------- concurrency

def storm(calls, width: int = 50):
    """Run callables with `width` in flight, released together by a barrier.

    Each worker uses its own fresh connection so that the listen backlog is
    exercised too (S-01). Returns results in input order (exceptions captured).
    """
    barrier = threading.Barrier(min(width, len(calls)))
    results = [None] * len(calls)

    def run(i):
        client = httpx.Client(timeout=30.0)
        try:
            if i < width:
                barrier.wait(timeout=30)
            results[i] = calls[i](client)
        except Exception as e:  # noqa: BLE001
            results[i] = e
        finally:
            client.close()

    with ThreadPoolExecutor(width) as ex:
        list(ex.map(run, range(len(calls))))
    return results


def as_(api: Api, client: httpx.Client) -> Api:
    return Api(api.token, user_id=api.user_id, handle=api.handle, client=client)
