"""Stage-2 helpers on top of the stage-1 `pf` module (HTTP only, derived from the ledger)."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pf
from pf import Api, new_key

AUTH_KEYS = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
             "amount", "captured_amount", "remaining_amount", "payment_ids", "currency",
             "note", "visibility", "status", "expires_at", "payment_id", "created_at"}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def in_hours(h: float) -> str:
    return iso(datetime.now(timezone.utc) + timedelta(hours=h))


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def seed_auth(aid, frm, to, amount, status="open", expires_at=None, note="", vis="public",
              **extra):
    return {"id": aid, "from_user_id": frm, "to_user_id": to, "amount": amount, "note": note,
            "visibility": vis, "status": status,
            "expires_at": expires_at or in_hours(2), **extra}


def fixture2(authorizations=None, ttl=None, **kw):
    f = pf.fixture(**kw)
    if authorizations is not None:
        f["authorizations"] = copy.deepcopy(authorizations)
    if ttl is not None:
        f["authorization_ttl_seconds"] = ttl
    return f


def me(api: Api) -> dict:
    m = api.me()
    assert m["balance"] == m["total"], f"R-206 balance != total: {m}"
    assert m["available"] == m["total"] - m["held"], f"R-206 available != total-held: {m}"
    assert m["available"] >= 0 and m["held"] >= 0, f"R-204 negative: {m}"
    return m


def authorize(api: Api, to_handle, amount, key=None, **extra):
    return api.post("/authorizations", {"to_handle": to_handle, "amount": amount, **extra},
                    key=key or new_key())


def capture(api: Api, aid, body=None, key=None):
    return api.post(f"/authorizations/{aid}/capture", {} if body is None else body,
                    key=key or new_key())


def void(api: Api, aid, body=None):
    return api.post(f"/authorizations/{aid}/void", {} if body is None else body)


def auths(api: Api, query: str = "") -> list[dict]:
    return pf._all_pages(api, "/authorizations" + (f"?{query}" if query else ""),
                         "authorizations")


def auth_of(api: Api, aid) -> dict:
    got = [a for a in auths(api) if a["authorization_id"] == aid]
    assert len(got) == 1, f"authorization {aid} not listed exactly once: {got}"
    return got[0]


def check_auth(a: dict, **expect):
    missing = AUTH_KEYS - set(a)
    assert not missing, f"authorization missing fields {missing}: {a}"
    pf.check_id(a["authorization_id"], "authorization_id")
    pf.check_ts(a["created_at"], "authorization.created_at")
    pf.check_ts(a["expires_at"], "authorization.expires_at")
    for k in ("amount", "captured_amount", "remaining_amount"):
        assert type(a[k]) is int, f"{k} must be a JSON integer: {a[k]!r}"
    assert a["status"] in ("open", "captured", "voided", "expired")
    assert isinstance(a["payment_ids"], list)
    for k, v in expect.items():
        assert a[k] == v, f"authorization.{k}: expected {v!r}, got {a[k]!r}"
    return a
