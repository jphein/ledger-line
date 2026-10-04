"""W1: model and fixture (R-11..R-20, S-03, S-12)."""
import pytest

import pf
from pf import Api, err, ok

L = pytest.mark.ledger


@L("R-11", "R-52")
@pytest.mark.parametrize("cur,mu", [("EUR", 2), ("JPY", 0), ("BHD", 3)])
def test_currency_from_fixture(cur, mu):
    w = pf.world(pf.fixture(currency=cur, minor_units=mu))
    me = w.ada.me()
    assert me["currency"] == cur and me["minor_units"] == mu
    p = ok(w.ada.pay("bob", 7), 201)
    assert p["currency"] == cur and p["amount"] == 7


@L("R-12", "S-03")
@pytest.mark.parametrize("raw", ["1000", "1000.0", "1e3", "1E3", "1.0e3", "10000e-1"])
def test_integral_number_forms_accepted(raw):
    w = pf.world()
    body = '{"to_handle": "bob", "amount": %s}' % raw
    r = w.ada.post("/payments", raw=body, key=pf.new_key())
    p = ok(r, 201)
    assert p["amount"] == 1000 and type(p["amount"]) is int, r.text
    assert '"amount": 1000.0' not in r.text and '"amount":1000.0' not in r.text
    assert w.ada.balance() == 9000
    q = ok(w.ada.post("/requests", raw='{"payer_handle": "bob", "amount": %s}' % raw,
                      key=pf.new_key()), 201)
    assert q["amount"] == 1000 and type(q["amount"]) is int


@L("R-12", "S-03", "R-27")
@pytest.mark.parametrize("raw", ["10.5", "\"1000\"", "true", "false", "null", "[1000]",
                                 "{}", "0.1", "1e-3"])
def test_non_integral_or_non_number_amount_422(raw):
    w = pf.world()
    r = w.ada.post("/payments", raw='{"to_handle": "bob", "amount": %s}' % raw,
                   key=pf.new_key())
    err(r, 422, "validation_failed")
    r = w.ada.post("/requests", raw='{"payer_handle": "bob", "amount": %s}' % raw,
                   key=pf.new_key())
    err(r, 422, "validation_failed")
    assert w.ada.balance() == 10000


@L("R-13", "R-16", "R-52")
def test_seeded_user_me():
    w = pf.world()
    assert w.ada.me() == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
                          "balance": 10000, "currency": "EUR", "minor_units": 2}
    assert w.dee.me()["balance"] == 0


@L("R-13")
def test_handle_unchanged_after_activity():
    w = pf.world()
    ok(w.ada.pay("bob", 1), 201)
    ok(w.bob.ask("ada", 1), 201)
    assert w.ada.me()["handle"] == "ada" and w.bob.me()["handle"] == "bob"


@L("R-15")
def test_new_user_zero_and_reachable():
    w = pf.world()
    s = ok(Api().post("/auth/signup", {"email": "newbie@x.com", "password": "12345678",
                                       "display_name": "Newbie"}), 201)
    nb = Api(s["token"])
    me = nb.me()
    assert me["balance"] == 0 and me["handle"] == "newbie"
    err(nb.pay("ada", 1), 409, "insufficient_funds")
    ok(w.ada.pay("newbie", 250), 201)
    assert nb.balance() == 250
    q = ok(w.bob.ask("newbie", 99999), 201)
    assert q["status"] == "pending"
    assert [r["request_id"] for r in nb.requests()] == [q["request_id"]]


@L("R-16")
def test_seeded_login_any_password():
    u = pf.user("u_x", "x", 1, password="pässwörd with spaces ✓")
    pf.reset(pf.fixture(users=[u, pf.ADA], payments=[], requests=[]))
    a = pf.login("x@example.com", "pässwörd with spaces ✓")
    assert a.me()["user_id"] == "u_x"
    err(Api().post("/auth/login", {"email": "x@example.com", "password": pf.PW}),
        401, "unauthenticated")


@L("R-17")
def test_seeded_balances_not_replayed():
    w = pf.world()
    assert w.ada.balance() == 10000
    assert w.bob.balance() == 2500
    assert w.cy.balance() == 500
    assert pf.total_balance(w) == w.total


@L("R-17")
def test_seeded_payments_returned_with_fixture_values():
    w = pf.world()
    p1 = [p for p in w.dee.activity() if p["payment_id"] == "p_1"]
    assert len(p1) == 1
    pf.check_payment(p1[0], from_user_id="u_ada", from_handle="ada", to_user_id="u_bob",
                     to_handle="bob", amount=500, note="coffee", visibility="public",
                     currency="EUR", request_id=None, settlement_id=None)
    p2 = [p for p in w.cy.activity() if p["payment_id"] == "p_2"]
    assert len(p2) == 1
    pf.check_payment(p2[0], from_user_id="u_bob", to_user_id="u_cy", amount=100,
                     note="secret gift", visibility="private")


@L("R-17")
def test_seeded_requests_returned_with_fixture_values():
    w = pf.world()
    reqs = {q["request_id"]: q for q in w.ada.requests()}
    assert set(reqs) == {"rq_1", "rq_2"}
    pf.check_request(reqs["rq_1"], requester_id="u_bob", requester_handle="bob",
                     payer_id="u_ada", payer_handle="ada", amount=1200, note="taxi",
                     status="pending", payment_id=None, currency="EUR")
    pf.check_request(reqs["rq_2"], requester_id="u_ada", payer_id="u_cy", amount=300,
                     status="declined")
    assert [q["request_id"] for q in w.dee.requests()] == []


@L("R-17")
def test_seeded_request_is_live():
    w = pf.world()
    p = ok(w.ada.pay_request("rq_1"), 201)
    assert p["request_id"] == "rq_1" and p["amount"] == 1200
    assert w.ada.balance() == 8800 and w.bob.balance() == 3700
    err(w.cy.pay_request("rq_2"), 409, "request_not_pending")


@L("R-18", "S-12")
def test_negative_balance_reset_422_changes_nothing():
    w = pf.world()
    ok(w.ada.pay("bob", 123), 201)
    bad = pf.fixture(users=[pf.user("u_q", "q", -1), pf.user("u_r", "r", 5)],
                     payments=[], requests=[])
    err(Api().post("/_test/reset", bad), 422, "validation_failed")
    assert w.ada.balance() == 10000 - 123          # old token still valid
    assert w.bob.balance() == 2500 + 123
    err(Api().post("/auth/login", {"email": "r@example.com", "password": pf.PW}),
        401, "unauthenticated")
    assert any(p["amount"] == 123 for p in w.ada.activity())


@L("R-19", "R-92")
def test_operator_default_empty():
    w = pf.world()
    body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}
    for a in (w.ada, w.bob):
        err(a.post("/settlements", body, key=pf.new_key()), 403, "forbidden")


@L("R-20")
def test_amount_max_boundary():
    big = pf.user("u_big", "big", 3_000_000_000)
    w = pf.world(pf.fixture(users=[big, pf.BOB], payments=[], requests=[]))
    ok(w.big.pay("bob", 1_000_000_000), 201)
    err(w.big.pay("bob", 1_000_000_001), 422, "validation_failed")
    assert w.big.balance() == 2_000_000_000
    assert w.bob.balance() == 1_000_002_500


@L("R-20")
def test_exact_arithmetic_near_2_53():
    near = 2**53 - 5
    a = pf.user("u_a", "a", near)
    b = pf.user("u_b", "b", 0)
    w = pf.world(pf.fixture(users=[a, b], payments=[], requests=[]))
    assert w.a.balance() == near
    ok(w.a.pay("b", 999_999_999), 201)
    ok(w.a.pay("b", 1), 201)
    assert w.a.balance() == near - 1_000_000_000
    assert w.b.balance() == 1_000_000_000
    assert pf.total_balance(w) == near
