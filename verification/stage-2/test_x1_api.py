"""X1: holds model, authorizations API, expiry, upgrade import, S-23 in container.

Lines: R-200..R-234, S-209..S-211, D-202..D-208 (I-200..I-204 in test_x1_storms.py).
"""
import json
import os
import re
import subprocess
import time
from datetime import timedelta
from pathlib import Path

import pytest

import pf
import pf2
from pf import Api, err, ok
from pf2 import authorize, auth_of, auths, capture, check_auth, me, seed_auth, void

L = pytest.mark.ledger
REPO = Path(__file__).resolve().parents[2]


def w2(**kw):
    """ada 10000, bob 2500, cy 500, dee 0, op 0 (operator)."""
    kw.setdefault("users", [pf.ADA, pf.BOB, pf.CY, pf.DEE, pf.OP])
    kw.setdefault("operators", ["u_op"])
    return pf.world(pf2.fixture2(**kw))


# ------------------------------------------------------------------ delivery

@L("R-200")
def test_stage2_folder_and_stage1_untouched():
    s2 = REPO / "stage-2"
    assert (s2 / "Dockerfile").is_file() and (s2 / "RUN.md").is_file()
    assert not (s2 / ".git").exists()
    out = subprocess.run(["git", "-C", str(REPO), "diff", "--stat",
                          "d0b69b4d32cd14edae0b64d559fcf1053d44f126", "HEAD", "--", "stage-1"],
                         capture_output=True, text=True)
    assert out.stdout.strip() == "", f"stage-1/ changed since the judged revision:\n{out.stdout}"


@L("R-201")
def test_ui_assets_served_locally():
    # raw client: an HTML screen is not subject to the JSON-API conventions (R-07/S-16)
    html = pf._shared.get(pf.BASE + "/", headers={"Accept": "text/html"})
    assert html.status_code == 200 and "text/html" in html.headers.get("content-type", "")
    text = html.text
    ext = re.findall(r"""(?:src|href)\s*=\s*["'](https?:)?//[^"']+""", text, re.I)
    assert not ext, f"external asset references: {ext}"
    assets = re.findall(r"""(?:src|href)\s*=\s*["']([^"'#?]+\.(?:js|css|woff2?|ttf|svg|png|ico))""",
                        text, re.I)
    for a in assets:
        url = a if a.startswith("/") else "/" + a
        r = pf._shared.get(pf.BASE + url)
        assert r.status_code == 200, f"asset {url}: {r.status_code}"
        if url.endswith(".css"):
            assert not re.search(r"url\(\s*['\"]?https?://|@import\s+['\"]?https?://", r.text), url
        if url.endswith(".js"):
            assert not re.search(r"""import\s*\(?\s*['"]https?://""", r.text), url


@L("R-202", "S-23")
def test_1000_user_reset_under_10s_in_container():
    users = [pf.user(f"u_{i}", f"k{i}", i) for i in range(1000)]
    t0 = time.monotonic()
    r = Api().post("/_test/reset", pf.fixture(users=users, payments=[], requests=[]),
                   budget=10.0)
    el = time.monotonic() - t0
    assert r.status_code == 204, r.text
    print(f"R-202 1000-user reset {el:.2f}s")
    assert el < 10.0, f"reset took {el:.2f}s"
    assert pf.login("k999@example.com").balance() == 999


# ------------------------------------------------------------------ /me and holds model

@L("R-206", "R-52")
def test_me_shape_no_holds():
    w = w2()
    m = w.ada.me()
    assert set(m) >= {"user_id", "display_name", "handle", "balance", "total", "available",
                      "held", "currency", "minor_units"}
    assert m["balance"] == m["total"] == m["available"] == 10000 and m["held"] == 0
    for k in ("balance", "total", "available", "held"):
        assert type(m[k]) is int


@L("R-203", "R-206", "R-219")
def test_hold_moves_no_money():
    w = w2()
    a = ok(authorize(w.ada, "bob", 2000), 201)
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (10000, 8000, 2000)
    assert me(w.bob)["total"] == 2500 and me(w.bob)["held"] == 0
    assert pf.total_balance(w) == w.total
    check_auth(a, status="open", amount=2000, remaining_amount=2000, captured_amount=0)


@L("R-204", "R-208")
def test_held_funds_cannot_fund_anything():
    w = w2()
    ok(authorize(w.cy, "bob", 400), 201)                       # cy: total 500, available 100
    err(w.cy.pay("bob", 101), 409, "insufficient_funds")
    err(authorize(w.cy, "bob", 101), 409, "insufficient_funds")
    q = ok(w.bob.ask("cy", 101), 201)
    err(w.cy.pay_request(q["request_id"]), 409, "insufficient_funds")
    err(w.op.post("/settlements", {"transfers": [
        {"from_handle": "cy", "to_handle": "dee", "amount": 101}]}, key=pf.new_key()),
        409, "insufficient_funds")
    ok(w.cy.pay("bob", 100), 201)                              # exactly available
    m = me(w.cy)
    assert (m["total"], m["available"], m["held"]) == (400, 0, 400)


@L("R-204", "R-208", "S-18")
def test_settlement_net_against_available():
    w = w2()
    ok(authorize(w.bob, "ada", 2400), 201)                     # bob available 100
    # bob receives 300 and sends 400: net -100 == available -> affordable
    ok(w.op.post("/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 300},
        {"from_handle": "bob", "to_handle": "cy", "amount": 400}]}, key=pf.new_key()), 201)
    m = me(w.bob)
    assert (m["total"], m["available"], m["held"]) == (2400, 0, 2400)
    err(w.op.post("/settlements", {"transfers": [
        {"from_handle": "bob", "to_handle": "cy", "amount": 1}]}, key=pf.new_key()),
        409, "insufficient_funds")


@L("R-204", "R-224")
def test_capture_may_spend_reserved_money():
    w = w2()
    a = ok(authorize(w.cy, "bob", 500), 201)                   # all of cy's money
    assert me(w.cy)["available"] == 0
    p = ok(capture(w.bob, a["authorization_id"]), 201)
    assert p["amount"] == 500
    m = me(w.cy)
    assert (m["total"], m["available"], m["held"]) == (0, 0, 0)
    assert me(w.bob)["total"] == 3000


@L("R-207", "R-211")
def test_payment_immediate_no_hold():
    w = w2()
    p = ok(w.ada.pay("bob", 100), 201)
    assert "authorization_id" in p and p["authorization_id"] is None
    assert p["request_id"] is None and p["settlement_id"] is None
    m = me(w.ada)
    assert m["held"] == 0 and m["total"] == m["available"] == 9900
    assert auths(w.ada) == []


@L("R-209", "R-211")
def test_request_pay_and_split_unchanged():
    w = w2()
    q = ok(w.bob.ask("ada", 50), 201)
    p = ok(w.ada.pay_request(q["request_id"]), 201)
    assert p["authorization_id"] is None and p["request_id"] == q["request_id"]
    assert me(w.ada)["held"] == 0
    s = ok(w.dee.post("/splits", {"amount": 10**9, "participant_handles": ["dee", "bob"]},
                      key=pf.new_key()), 201)                  # no balance check
    assert [x["amount"] for x in s["shares"]] == [500_000_000, 500_000_000]


# ------------------------------------------------------------------ fixture

@L("R-212", "D-205", "R-219")
def test_default_ttl_600():
    w = w2()
    a = ok(authorize(w.ada, "bob", 1), 201)
    c, e = pf2.parse_ts(a["created_at"]), pf2.parse_ts(a["expires_at"])
    assert e - c == timedelta(seconds=600), (a["created_at"], a["expires_at"])


@L("R-212", "D-205")
def test_fixture_ttl_applies():
    w = w2(ttl=1234)
    a = ok(authorize(w.ada, "bob", 1), 201)
    assert pf2.parse_ts(a["expires_at"]) - pf2.parse_ts(a["created_at"]) == timedelta(seconds=1234)


@L("R-212", "S-22")
@pytest.mark.parametrize("ttl", [0, -1, 1.5, "600", True, None, [600]])
def test_bad_ttl_reset_422_changes_nothing(ttl):
    w = w2()
    ok(w.ada.pay("bob", 7), 201)
    f = pf2.fixture2(ttl=600)
    f["authorization_ttl_seconds"] = ttl
    err(Api().post("/_test/reset", f), 422, "validation_failed")
    assert me(w.ada)["total"] == 9993


@L("R-213", "R-214", "R-216")
def test_seeded_authorizations():
    seeded = [seed_auth("a_open", "u_ada", "u_bob", 2000, note="deposit", vis="private"),
              seed_auth("a_cap", "u_ada", "u_bob", 300, status="captured"),
              seed_auth("a_void", "u_ada", "u_cy", 400, status="voided"),
              seed_auth("a_exp", "u_ada", "u_cy", 500, status="expired")]
    w = w2(authorizations=seeded)
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (10000, 8000, 2000)
    by = {a["authorization_id"]: a for a in auths(w.ada)}
    assert set(by) == {"a_open", "a_cap", "a_void", "a_exp"}
    check_auth(by["a_open"], status="open", amount=2000, from_user_id="u_ada",
               to_user_id="u_bob", note="deposit", visibility="private",
               remaining_amount=2000, from_handle="ada", to_handle="bob")
    assert by["a_open"]["expires_at"] and pf2.parse_ts(by["a_open"]["expires_at"]) == \
        pf2.parse_ts(seeded[0]["expires_at"])
    for aid, st in (("a_cap", "captured"), ("a_void", "voided"), ("a_exp", "expired")):
        assert by[aid]["status"] == st and by[aid]["remaining_amount"] == 0
    assert {a["authorization_id"] for a in auths(w.bob)} == {"a_open", "a_cap"}
    assert auths(w.dee) == []


@L("R-213")
def test_fixture_without_authorizations_key():
    f = pf.fixture()
    assert "authorizations" not in f
    w = pf.world(f)
    assert auths(w.ada) == [] and me(w.ada)["held"] == 0


@L("R-215", "S-12")
def test_seeded_holds_over_balance_422():
    w = w2()
    ok(w.ada.pay("bob", 7), 201)
    bad = pf2.fixture2(authorizations=[seed_auth("a1", "u_cy", "u_bob", 300),
                                       seed_auth("a2", "u_cy", "u_ada", 201)])
    err(Api().post("/_test/reset", bad), 422, "validation_failed")
    assert me(w.ada)["total"] == 9993                          # old state and token intact
    okf = pf2.fixture2(authorizations=[seed_auth("a1", "u_cy", "u_bob", 300),
                                       seed_auth("a2", "u_cy", "u_ada", 200)])
    pf.reset(okf)
    m = me(pf.login("cy@example.com"))
    assert (m["total"], m["available"], m["held"]) == (500, 0, 500)


@L("S-211", "R-215", "R-217")
def test_expired_seeded_hold_not_counted():
    f = pf2.fixture2(authorizations=[seed_auth("a1", "u_cy", "u_bob", 5000,
                                               expires_at=pf2.in_hours(-2))])
    pf.reset(f)
    cy = pf.login("cy@example.com")
    m = me(cy)
    assert (m["total"], m["available"], m["held"]) == (500, 500, 0)
    assert auth_of(cy, "a1")["status"] == "expired"


@L("R-216", "R-215")
def test_non_open_seeded_do_not_count_toward_limit():
    f = pf2.fixture2(authorizations=[seed_auth("a1", "u_cy", "u_bob", 5000, status="captured"),
                                     seed_auth("a2", "u_cy", "u_bob", 5000, status="voided"),
                                     seed_auth("a3", "u_cy", "u_bob", 5000, status="expired"),
                                     seed_auth("a4", "u_cy", "u_bob", 500)])
    pf.reset(f)
    m = me(pf.login("cy@example.com"))
    assert (m["available"], m["held"]) == (0, 500)


# ------------------------------------------------------------------ expiry

@L("R-217", "I-204", "S-210", "D-202")
def test_created_auth_expires_on_clock_without_writes():
    w = w2(ttl=2)
    a = ok(authorize(w.cy, "bob", 300), 201)
    assert me(w.cy)["held"] == 300
    deadline = pf2.parse_ts(a["expires_at"])
    from datetime import datetime, timezone
    while datetime.now(timezone.utc) <= deadline + timedelta(milliseconds=300):
        time.sleep(0.1)
    m = me(w.cy)
    assert (m["total"], m["available"], m["held"]) == (500, 500, 0)
    assert auth_of(w.cy, a["authorization_id"])["status"] == "expired"
    assert [x["authorization_id"] for x in auths(w.cy, "status=expired")] == [a["authorization_id"]]
    assert auths(w.cy, "status=open") == []
    err(capture(w.bob, a["authorization_id"]), 409, "authorization_expired")
    err(void(w.cy, a["authorization_id"]), 409, "authorization_not_open")
    ok(w.cy.pay("bob", 500), 201)                              # released funds are spendable


@L("R-217")
def test_seeded_open_hold_in_past_is_expired_from_reset():
    w = w2(authorizations=[seed_auth("a_old", "u_ada", "u_bob", 1000,
                                     expires_at=pf2.in_hours(-1.5))])
    assert me(w.ada)["held"] == 0
    assert auth_of(w.bob, "a_old")["status"] == "expired"
    err(capture(w.bob, "a_old"), 409, "authorization_expired")


@L("R-218", "R-225", "R-229")
def test_void_after_partial_capture_releases_remainder():
    w = w2()
    a = ok(authorize(w.ada, "bob", 1000), 201)
    aid = a["authorization_id"]
    p1 = ok(capture(w.bob, aid, {"amount": 300, "final": False}), 201)
    v = ok(void(w.ada, aid))
    check_auth(v, status="voided", captured_amount=300, remaining_amount=0,
               payment_ids=[p1["payment_id"]])
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (9700, 9700, 0)
    assert me(w.bob)["total"] == 2800


@L("R-218", "R-217")
def test_expiry_after_partial_capture_keeps_captures():
    w = w2(ttl=2)
    a = ok(authorize(w.ada, "bob", 1000), 201)
    aid = a["authorization_id"]
    p1 = ok(capture(w.bob, aid, {"amount": 250, "final": False}), 201)
    time.sleep(3.2)
    got = auth_of(w.ada, aid)
    check_auth(got, status="expired", captured_amount=250, remaining_amount=0,
               payment_ids=[p1["payment_id"]])
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (9750, 9750, 0)


# ------------------------------------------------------------------ POST /authorizations

@L("R-219", "R-54", "D-206")
def test_authorize_201_shape_and_defaults():
    w = w2()
    a = ok(authorize(w.ada, "bob", 2000), 201)
    check_auth(a, from_user_id="u_ada", from_handle="ada", to_user_id="u_bob",
               to_handle="bob", amount=2000, captured_amount=0, remaining_amount=2000,
               payment_ids=[], currency="EUR", note="", visibility="public", status="open",
               payment_id=None)
    b = ok(authorize(w.ada, "cy", 5, note="deposit ✓", visibility="private"), 201)
    assert b["note"] == "deposit ✓" and b["visibility"] == "private"
    assert b["authorization_id"] != a["authorization_id"]


@L("R-220")
def test_authorize_errors():
    w = w2()
    err(authorize(w.cy, "bob", 501), 409, "insufficient_funds")
    for amt in (0, -1, 1_000_000_001, 1.5, "10", True, None):
        err(authorize(w.ada, "bob", amt), 422, "validation_failed")
    err(authorize(w.ada, "ada", 10), 422, "self_payment")
    err(authorize(w.ada, "bob", 10, note="n" * 201), 422, "validation_failed")
    err(authorize(w.ada, "bob", 10, note=None), 422, "validation_failed")
    err(authorize(w.ada, "bob", 10, visibility="secret"), 422, "validation_failed")
    err(authorize(w.ada, "ghost", 10), 404, "not_found")
    ok(authorize(w.ada, "bob", 10, note="n" * 200), 201)
    ok(authorize(w.cy, "bob", 500), 201)                       # exactly available
    assert me(w.cy)["available"] == 0
    assert me(w.ada)["held"] == 10


@L("R-210", "R-23", "R-29")
def test_authorization_paths_require_key():
    w = w2()
    err(w.ada.post("/authorizations", {"to_handle": "bob", "amount": 1}), 400,
        "missing_idempotency_key")
    err(w.ada.post("/authorizations", {"to_handle": "bob", "amount": 1}, key=""), 400,
        "missing_idempotency_key")
    err(w.ada.post("/authorizations", {"to_handle": "bob", "amount": 1}, key="k" * 256), 422,
        "validation_failed")
    a = ok(authorize(w.ada, "bob", 100), 201)
    err(w.bob.post(f"/authorizations/{a['authorization_id']}/capture", {}), 400,
        "missing_idempotency_key")
    assert me(w.ada)["held"] == 100


@L("R-210", "R-44", "R-45", "R-46", "R-49", "R-51")
def test_authorization_idempotency():
    w = w2()
    k = pf.new_key()
    a = ok(authorize(w.ada, "bob", 700, key=k), 201)
    assert ok(authorize(w.ada, "bob", 700, key=k), 200) == a
    err(authorize(w.ada, "bob", 701, key=k), 409, "idempotency_key_reuse")
    err(authorize(w.ada, "bob", -1, key=k), 409, "idempotency_key_reuse")
    assert me(w.ada)["held"] == 700 and len(auths(w.ada)) == 1
    k2 = pf.new_key()
    err(authorize(w.cy, "bob", 9999, key=k2), 409, "insufficient_funds")
    ok(authorize(w.cy, "bob", 9, key=k2), 201)                 # 4xx key reusable
    ok(authorize(w.bob, "ada", 700, key=k), 201)               # per-user scope


@L("R-221", "R-74")
def test_open_authorization_not_in_feed():
    w = w2()
    before = {h: {p["payment_id"] for p in a.activity()} for h, a in w.users.items()}
    ok(authorize(w.ada, "bob", 100), 201)
    ok(authorize(w.ada, "cy", 100, visibility="private"), 201)
    after = {h: {p["payment_id"] for p in a.activity()} for h, a in w.users.items()}
    assert before == after


# ------------------------------------------------------------------ capture

@L("R-222", "R-223", "R-224", "R-211")
def test_capture_full_default():
    w = w2()
    a = ok(authorize(w.ada, "bob", 2000, note="deposit", visibility="private"), 201)
    aid = a["authorization_id"]
    p = ok(capture(w.bob, aid), 201)
    pf.check_payment(p, from_user_id="u_ada", from_handle="ada", to_user_id="u_bob",
                     to_handle="bob", amount=2000, note="deposit", visibility="private",
                     request_id=None, settlement_id=None, currency="EUR")
    assert p["authorization_id"] == aid
    got = auth_of(w.ada, aid)
    check_auth(got, status="captured", captured_amount=2000, remaining_amount=0,
               payment_id=p["payment_id"], payment_ids=[p["payment_id"]])
    assert me(w.ada)["total"] == 8000 and me(w.ada)["held"] == 0
    assert me(w.bob)["total"] == 4500
    err(capture(w.bob, aid), 409, "authorization_not_open")
    err(capture(w.bob, aid, {"amount": 1}), 409, "authorization_not_open")


@L("R-224", "R-226")
def test_partial_final_capture_releases_remainder_same_step():
    w = w2()
    a = ok(authorize(w.ada, "bob", 2000), 201)
    p = ok(capture(w.bob, a["authorization_id"], {"amount": 1500}), 201)
    assert p["amount"] == 1500
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (8500, 8500, 0)
    check_auth(auth_of(w.bob, a["authorization_id"]), status="captured",
               captured_amount=1500, remaining_amount=0)


@L("R-223", "R-74")
def test_capture_payment_follows_feed_rule():
    w = w2()
    priv = ok(authorize(w.ada, "bob", 10, visibility="private"), 201)
    pub = ok(authorize(w.ada, "bob", 20), 201)
    pp = ok(capture(w.bob, priv["authorization_id"]), 201)["payment_id"]
    pu = ok(capture(w.bob, pub["authorization_id"]), 201)["payment_id"]
    ids = {h: {p["payment_id"] for p in a.activity()} for h, a in w.users.items()}
    assert pp in ids["ada"] and pp in ids["bob"] and pp not in ids["cy"]
    assert all(pu in s for s in ids.values())
    item = [p for p in w.cy.activity() if p["payment_id"] == pu][0]
    assert item["authorization_id"] == pub["authorization_id"]


@L("R-222", "R-67", "R-46")
def test_capture_empty_vs_explicit_amount_differ():
    w = w2()
    a = ok(authorize(w.ada, "bob", 2000), 201)
    k = pf.new_key()
    p = ok(capture(w.bob, a["authorization_id"], {}, key=k), 201)
    err(capture(w.bob, a["authorization_id"], {"amount": 2000}, key=k), 409,
        "idempotency_key_reuse")
    assert ok(capture(w.bob, a["authorization_id"], {}, key=k), 200) == p


@L("R-225", "R-226")
def test_extended_capture_mode():
    w = w2()
    a = ok(authorize(w.ada, "bob", 2000), 201)
    aid = a["authorization_id"]
    p1 = ok(capture(w.bob, aid, {"amount": 700, "final": False}), 201)
    g = auth_of(w.bob, aid)
    check_auth(g, status="open", captured_amount=700, remaining_amount=1300,
               payment_id=p1["payment_id"], payment_ids=[p1["payment_id"]])
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (9300, 8000, 1300)
    err(capture(w.bob, aid, {"amount": 1301, "final": False}), 422,
        "capture_exceeds_authorization")
    p2 = ok(capture(w.bob, aid, {"amount": 300, "final": False}), 201)
    p3 = ok(capture(w.bob, aid, {"final": False}), 201)       # omitted -> remainder (1000)
    assert p3["amount"] == 1000
    g = auth_of(w.bob, aid)
    check_auth(g, status="captured", captured_amount=2000, remaining_amount=0,
               payment_id=p3["payment_id"],
               payment_ids=[p1["payment_id"], p2["payment_id"], p3["payment_id"]])
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (8000, 8000, 0)
    err(capture(w.bob, aid, {"amount": 1, "final": False}), 409, "authorization_not_open")


@L("R-225")
def test_entire_remainder_with_final_false_closes():
    w = w2()
    a = ok(authorize(w.ada, "bob", 500), 201)
    ok(capture(w.bob, a["authorization_id"], {"amount": 500, "final": False}), 201)
    assert auth_of(w.ada, a["authorization_id"])["status"] == "captured"
    assert me(w.ada)["held"] == 0


@L("R-225", "R-224")
def test_final_after_partial_releases_rest():
    w = w2()
    a = ok(authorize(w.ada, "bob", 1000), 201)
    aid = a["authorization_id"]
    ok(capture(w.bob, aid, {"amount": 100, "final": False}), 201)
    ok(capture(w.bob, aid, {"amount": 100, "final": True}), 201)
    check_auth(auth_of(w.ada, aid), status="captured", captured_amount=200, remaining_amount=0)
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (9800, 9800, 0)


@L("R-227", "R-50", "R-45")
def test_capture_replay_returns_original_after_changes():
    w = w2()
    a = ok(authorize(w.ada, "bob", 1000), 201)
    aid = a["authorization_id"]
    k = pf.new_key()
    body = {"amount": 100, "final": False}
    p = ok(capture(w.bob, aid, body, key=k), 201)
    ok(capture(w.bob, aid, {"amount": 50, "final": False}), 201)
    ok(void(w.ada, aid))
    assert ok(capture(w.bob, aid, body, key=k), 200) == p
    assert me(w.ada)["total"] == 9850 and me(w.bob)["total"] == 2650
    k2 = pf.new_key()
    a2 = ok(authorize(w.ada, "bob", 10, key=k2), 201)
    ok(capture(w.bob, a2["authorization_id"]), 201)
    assert ok(authorize(w.ada, "bob", 10, key=k2), 200) == a2   # original 'open' body


@L("R-228", "D-203")
def test_capture_errors():
    w = w2()
    a = ok(authorize(w.ada, "bob", 1000), 201)
    aid = a["authorization_id"]
    err(capture(w.bob, "a_nope"), 404, "not_found")
    err(capture(w.ada, aid), 403, "forbidden")                 # payer
    err(capture(w.cy, aid), 403, "forbidden")                  # third party
    for amt in (0, -5, 1.5, "100", True, None):
        err(capture(w.bob, aid, {"amount": amt}), 422, "validation_failed")
    err(capture(w.bob, aid, {"amount": 1001}), 422, "capture_exceeds_authorization")
    err(capture(w.bob, aid, {"amount": 1_000_000_001}), 422)
    v = ok(authorize(w.ada, "bob", 10), 201)
    ok(void(w.ada, v["authorization_id"]))
    err(capture(w.bob, v["authorization_id"]), 409, "authorization_not_open")
    assert me(w.ada)["held"] == 1000 and me(w.ada)["total"] == 10000


@L("S-209", "R-22", "D-203")
@pytest.mark.parametrize("final", ['"false"', "0", "1", "null", "[]", '"true"'])
def test_capture_final_wrong_type_400(final):
    w = w2()
    a = ok(authorize(w.ada, "bob", 1000), 201)
    r = w.bob.post(f"/authorizations/{a['authorization_id']}/capture",
                   raw='{"amount": 10, "final": %s}' % final, key=pf.new_key())
    err(r, 400, "malformed_request")
    assert me(w.ada)["held"] == 1000


# ------------------------------------------------------------------ void

@L("R-229", "D-204")
def test_void_flow():
    w = w2()
    a = ok(authorize(w.ada, "bob", 1000), 201)
    aid = a["authorization_id"]
    err(void(w.bob, aid), 403, "forbidden")                    # receiver
    err(void(w.cy, aid), 403, "forbidden")                     # third party
    err(void(w.ada, "a_nope"), 404, "not_found")
    v = ok(void(w.ada, aid))
    check_auth(v, status="voided", remaining_amount=0, captured_amount=0)
    assert me(w.ada)["held"] == 0 and me(w.ada)["available"] == 10000
    assert ok(void(w.ada, aid)) == v                           # twice: 200 current state
    c = ok(authorize(w.ada, "bob", 10), 201)
    ok(capture(w.bob, c["authorization_id"]), 201)
    err(void(w.ada, c["authorization_id"]), 409, "authorization_not_open")
    r = w.ada.request("POST", f"/authorizations/{aid}/void")   # no body at all
    assert r.status_code == 200


# ------------------------------------------------------------------ GET /authorizations

@L("R-230")
def test_list_filters_and_order():
    w = w2(authorizations=[seed_auth("a_seed", "u_bob", "u_ada", 100)])
    made = []
    for to in ("bob", "cy", "dee"):
        made.append(ok(authorize(w.ada, to, 10), 201)["authorization_id"])
        time.sleep(1.1)
    ok(void(w.ada, made[1]))
    ids = [a["authorization_id"] for a in auths(w.ada)]
    assert ids[:3] == made[::-1] and ids[3] == "a_seed", ids
    assert {a["authorization_id"] for a in auths(w.ada, "direction=outgoing")} == set(made)
    assert {a["authorization_id"] for a in auths(w.ada, "direction=incoming")} == {"a_seed"}
    assert {a["authorization_id"] for a in auths(w.ada, "status=voided")} == {made[1]}
    assert {a["authorization_id"] for a in auths(w.ada, "status=open")} == \
        {made[0], made[2], "a_seed"}
    assert {a["authorization_id"] for a in auths(w.ada, "direction=outgoing&status=open")} == \
        {made[0], made[2]}
    assert auths(w.ada, "status=captured") == []
    assert {a["authorization_id"] for a in auths(w.cy)} == {made[1]}
    assert {a["authorization_id"] for a in auths(w.bob)} == {made[0], "a_seed"}


@L("R-230", "R-28", "R-29")
@pytest.mark.parametrize("q", ["direction=sideways", "status=pending", "status=OPEN",
                               "limit=0", "limit=201", "limit=4.0", "offset=-1", "limit=1e2"])
def test_list_bad_query_422(q):
    w = w2()
    err(w.ada.get(f"/authorizations?{q}"), 422, "validation_failed")


@L("R-230", "S-10")
def test_list_pagination():
    w = w2()
    for i in range(5):
        ok(authorize(w.ada, "bob", 1 + i), 201)
    full = ok(w.ada.get("/authorizations"))
    assert len(full["authorizations"]) == 5 and full["has_more"] is False
    for limit, offset, n, more in [(5, 0, 5, False), (4, 0, 4, True), (2, 3, 2, False),
                                   (2, 2, 2, True), (3, 5, 0, False)]:
        b = ok(w.ada.get(f"/authorizations?limit={limit}&offset={offset}"))
        assert len(b["authorizations"]) == n and b["has_more"] is more, (limit, offset, b)


@L("R-230", "R-24")
def test_list_needs_auth():
    w2()
    err(Api().get("/authorizations"), 401, "unauthenticated")
    err(Api().post("/authorizations", {"to_handle": "bob", "amount": 1}, key="k"), 401)


# ------------------------------------------------------------------ upgrade and export

@L("R-231", "S-06", "S-08")
def test_import_stage1_export():
    path = os.environ.get("STAGE1_EXPORT")
    if not path or not Path(path).is_file():
        pytest.skip("STAGE1_EXPORT not provided (made by make_s1_export.py against stage-1)")
    bundle = json.loads(Path(path).read_text())
    pf.reset(pf2.fixture2())
    r = Api().post("/_test/import", bundle["export"])
    assert r.status_code == 204, r.text
    ada, bob = Api(bundle["tokens"]["ada"]), Api(bundle["tokens"]["bob"])
    m = me(ada)
    assert m["total"] == bundle["balances"]["ada"] and m["held"] == 0
    assert ok(ada.pay("bob", bundle["payment_body"]["amount"], key=bundle["payment_key"],
                      **{k: v for k, v in bundle["payment_body"].items()
                         if k not in ("to_handle", "amount")}), 200) == bundle["payment"]
    ok(ada.pay("bob", 1, key=bundle["failed_key"]), 201)     # failed stage-1 key reusable
    p = ok(ada.pay_request(bundle["pending_request_id"]), 201)
    assert p["authorization_id"] is None
    assert auths(ada) == []
    a = ok(authorize(ada, "bob", 1), 201)                      # default ttl 600 after upgrade
    assert pf2.parse_ts(a["expires_at"]) - pf2.parse_ts(a["created_at"]) == timedelta(seconds=600)
    ok(capture(bob, a["authorization_id"]), 201)


@L("R-233", "R-89", "I-07")
def test_stage2_export_round_trip_with_authorizations():
    w = w2(ttl=900)
    a_open = ok(authorize(w.ada, "bob", 1000), 201)["authorization_id"]
    a_part = ok(authorize(w.ada, "cy", 800, visibility="private"), 201)["authorization_id"]
    k = pf.new_key()
    p1 = ok(capture(w.cy, a_part, {"amount": 300, "final": False}, key=k), 201)
    a_void = ok(authorize(w.bob, "ada", 50), 201)["authorization_id"]
    ok(void(w.bob, a_void))

    def obs():
        return {h: (me(a), sorted(json.dumps(x, sort_keys=True) for x in auths(a)),
                    sorted(p["payment_id"] for p in a.activity()))
                for h, a in w.users.items()}
    before = obs()
    e = ok(Api().get("/_test/export"))
    pf.reset(pf2.fixture2())
    assert Api().post("/_test/import", e).status_code == 204
    assert obs() == before
    assert ok(capture(w.cy, a_part, {"amount": 300, "final": False}, key=k), 200) == p1
    p2 = ok(capture(w.cy, a_part), 201)
    check_auth(auth_of(w.cy, a_part), status="captured", captured_amount=800,
               payment_ids=[p1["payment_id"], p2["payment_id"]])
    n = ok(authorize(w.ada, "bob", 1), 201)
    assert pf2.parse_ts(n["expires_at"]) - pf2.parse_ts(n["created_at"]) == timedelta(seconds=900)
    assert n["authorization_id"] not in {a_open, a_part, a_void}
    e2 = ok(Api().get("/_test/export"))
    assert Api().post("/_test/import", e2).status_code == 204


@L("R-233", "R-87", "S-17")
def test_import_with_bad_authorization_state_422():
    w = w2()
    ok(authorize(w.ada, "bob", 100), 201)
    e = ok(Api().get("/_test/export"))
    bad = json.loads(json.dumps(e))
    bad["state"] = {k: "garbage" for k in e["state"]}
    err(Api().post("/_test/import", bad), 422, "validation_failed")
    assert me(w.ada)["held"] == 100


# ------------------------------------------------------------------ amendments 17:36

@L("R-227", "R-46")
def test_capture_body_with_explicit_default_final_is_different():
    w = w2()
    a = ok(authorize(w.ada, "bob", 2000), 201)
    k = pf.new_key()
    ok(capture(w.bob, a["authorization_id"], {"amount": 700}, key=k), 201)
    err(capture(w.bob, a["authorization_id"], {"amount": 700, "final": True}, key=k), 409,
        "idempotency_key_reuse")
    assert me(w.bob)["total"] == 3200


@L("S-215", "R-202", "S-23")
def test_1000_distinct_passwords_reset_under_10s():
    users = [pf.user(f"u_{i}", f"d{i}", 1, password=f"pw-{i}-distinct") for i in range(1000)]
    t0 = time.monotonic()
    r = Api().post("/_test/reset", pf.fixture(users=users, payments=[], requests=[]),
                   budget=10.0)
    el = time.monotonic() - t0
    assert r.status_code == 204, r.text
    print(f"S-215 1000 distinct passwords reset {el:.2f}s")
    assert el < 10.0, f"reset took {el:.2f}s"
    assert pf.login("d777@example.com", "pw-777-distinct").balance() == 1
    err(Api().post("/auth/login", {"email": "d777@example.com", "password": "pw-778-distinct"}),
        401, "unauthenticated")


@L("S-216", "S-210", "R-228")
def test_ttl_1_capture_now_then_expired():
    w = w2(ttl=1)
    a = ok(authorize(w.ada, "bob", 100), 201)
    ok(capture(w.bob, a["authorization_id"], {"amount": 10, "final": False}), 201)
    time.sleep(1.5)
    err(capture(w.bob, a["authorization_id"]), 409, "authorization_expired")
    m = me(w.ada)
    assert (m["total"], m["available"], m["held"]) == (9990, 9990, 0)


def _bad_auth_fixtures():
    good = seed_auth("a1", "u_ada", "u_bob", 100)
    cases = {
        "unknown_from": dict(good, from_user_id="u_x"),
        "unknown_to": dict(good, to_user_id="u_x"),
        "from_eq_to": dict(good, to_user_id="u_ada"),
        "amount_0": dict(good, amount=0),
        "amount_big": dict(good, amount=1_000_000_001),
        "amount_frac": dict(good, amount=1.5),
        "amount_str": dict(good, amount="100"),
        "bad_visibility": dict(good, visibility="secret"),
        "bad_status": dict(good, status="pending"),
        "bad_expires": dict(good, expires_at="tomorrow"),
        "expires_no_offset": dict(good, expires_at="2030-01-01T00:00:00"),
    }
    out = {k: [v] for k, v in cases.items()}
    out["duplicate_id"] = [good, dict(good, to_user_id="u_cy")]
    return out


@L("S-217", "S-22")
@pytest.mark.parametrize("name", list(_bad_auth_fixtures()))
def test_bad_seeded_authorization_422(name):
    w = w2()
    ok(w.ada.pay("bob", 7), 201)
    err(Api().post("/_test/reset", pf2.fixture2(authorizations=_bad_auth_fixtures()[name])),
        422, "validation_failed")
    assert me(w.ada)["total"] == 9993


@L("S-217", "D-206")
def test_seeded_captured_without_captured_amount_ok():
    w = w2(authorizations=[seed_auth("a1", "u_ada", "u_bob", 100, status="captured")])
    a = auth_of(w.ada, "a1")
    assert a["status"] == "captured" and type(a["captured_amount"]) is int
    assert a["remaining_amount"] == 0 and isinstance(a["payment_ids"], list)


@L("D-211", "R-231")
def test_imported_stage1_payments_have_null_authorization_id():
    path = os.environ.get("STAGE1_EXPORT")
    if not path or not Path(path).is_file():
        pytest.skip("STAGE1_EXPORT not provided")
    bundle = json.loads(Path(path).read_text())
    pf.reset(pf2.fixture2())
    assert Api().post("/_test/import", bundle["export"]).status_code == 204
    ada = Api(bundle["tokens"]["ada"])
    feed = ada.activity()
    assert feed and all("authorization_id" in p and p["authorization_id"] is None for p in feed)
    replay = ok(ada.pay("bob", bundle["payment_body"]["amount"], key=bundle["payment_key"],
                        **{k: v for k, v in bundle["payment_body"].items()
                           if k not in ("to_handle", "amount")}), 200)
    assert replay == bundle["payment"]                          # stored response, not rewritten
