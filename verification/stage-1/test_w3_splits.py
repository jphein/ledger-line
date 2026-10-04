"""W3: splits and rounding (R-76..R-83, R-41 for /splits)."""
import pytest

import pf
from pf import err, ok

L = pytest.mark.ledger


def split_world():
    return pf.world(pf.fixture(users=[pf.ADA, pf.BOB, pf.CY, pf.DEE, pf.EVE, pf.FAY],
                               payments=[], requests=[]))


def split(api, amount, handles, key=None, **extra):
    return api.post("/splits", {"amount": amount, "participant_handles": handles, **extra},
                    key=key or pf.new_key())


@L("R-76", "R-77", "R-78")
def test_split_shape_caller_included():
    w = split_world()
    s = ok(split(w.ada, 3000, ["ada", "bob", "cy"], note="dinner"), 201)
    assert set(s) >= {"split_id", "amount", "currency", "note", "shares", "requests",
                      "created_at"}
    pf.check_id(s["split_id"])
    pf.check_ts(s["created_at"])
    assert s["amount"] == 3000 and s["currency"] == "EUR" and s["note"] == "dinner"
    assert s["shares"] == [{"handle": "ada", "amount": 1000},
                           {"handle": "bob", "amount": 1000},
                           {"handle": "cy", "amount": 1000}]
    assert [q["payer_handle"] for q in s["requests"]] == ["bob", "cy"]
    for q in s["requests"]:
        pf.check_request(q, requester_id="u_ada", requester_handle="ada", amount=1000,
                         status="pending", payment_id=None, currency="EUR")
    # the requests are real and visible to their parties
    assert {q["request_id"] for q in s["requests"]} <= {q["request_id"] for q in
                                                       w.ada.requests("direction=outgoing")}
    assert [q["request_id"] for q in w.bob.requests()] == [s["requests"][0]["request_id"]]
    assert w.ada.balance() == 10000


@L("R-77", "R-78")
def test_split_caller_omitted_and_order():
    w = split_world()
    s = ok(split(w.ada, 1000, ["cy", "bob", "dee"]), 201)
    assert s["shares"] == [{"handle": "cy", "amount": 334}, {"handle": "bob", "amount": 333},
                           {"handle": "dee", "amount": 333}]
    assert [(q["payer_handle"], q["amount"]) for q in s["requests"]] == \
        [("cy", 334), ("bob", 333), ("dee", 333)]
    assert s["note"] == ""


@L("R-77", "R-78")
def test_split_caller_in_middle():
    w = split_world()
    s = ok(split(w.bob, 10, ["ada", "bob", "cy"]), 201)
    assert [x["amount"] for x in s["shares"]] == [4, 3, 3]
    assert [x["handle"] for x in s["shares"]] == ["ada", "bob", "cy"]
    assert [(q["payer_handle"], q["amount"]) for q in s["requests"]] == [("ada", 4), ("cy", 3)]


@L("R-81")
@pytest.mark.parametrize("amount,handles,shares", [
    (1000, ["bob", "cy", "dee"], [334, 333, 333]),
    (1, ["bob", "cy", "dee"], [1, 0, 0]),
    (10, ["bob", "cy", "dee"], [4, 3, 3]),
    (999, ["bob", "cy", "dee"], [333, 333, 333]),
    (5, ["ada", "bob", "cy", "dee", "eve"], [1, 1, 1, 1, 1]),
    (7, ["bob", "cy", "dee", "eve", "fay"], [2, 2, 1, 1, 1]),
    (1_000_000_000, ["bob", "cy", "dee"], [333333334, 333333333, 333333333]),
    (2, ["bob", "cy", "dee", "eve", "fay"], [1, 1, 0, 0, 0]),
    (1, ["bob"], [1]),
])
def test_rounding_table(amount, handles, shares):
    w = split_world()
    s = ok(split(w.ada, amount, handles), 201)
    assert [x["amount"] for x in s["shares"]] == shares
    assert sum(x["amount"] for x in s["shares"]) == amount
    assert all(type(x["amount"]) is int for x in s["shares"])


@L("R-79")
@pytest.mark.parametrize("amount", [0, -1, 1_000_000_001, 1.5, "10", True])
def test_split_amount_422(amount):
    w = split_world()
    err(split(w.ada, amount, ["bob"]), 422, "validation_failed")
    assert w.bob.requests() == []


@L("R-79")
def test_split_errors():
    w = split_world()
    err(split(w.ada, 10, []), 422, "validation_failed")
    err(split(w.ada, 10, ["bob", "bob"]), 422, "validation_failed")
    err(split(w.ada, 10, ["ada", "bob", "ada"]), 422, "validation_failed")
    err(split(w.ada, 10, ["bob"], note="n" * 201), 422, "validation_failed")
    ok(split(w.ada, 10, ["bob"], note="n" * 200), 201)
    err(split(w.ada, 10, ["bob", "ghost"]), 404, "not_found")
    err(split(w.ada, 10, ["ghost"]), 404, "not_found")
    err(w.ada.post("/splits", {"amount": 10}, key=pf.new_key()), 422, "validation_failed")
    err(w.ada.post("/splits", {"participant_handles": ["bob"]}, key=pf.new_key()), 422,
        "validation_failed")
    err(split(w.ada, 10, ["bob"], note=None), 422, "validation_failed")
    assert len(w.bob.requests()) == 1


@L("R-79", "R-22")
@pytest.mark.parametrize("val", ['"bob"', "5", "{}", '[5]', '["bob", null]'])
def test_split_handles_wrong_type_400(val):
    w = split_world()
    r = w.ada.post("/splits", raw='{"amount": 10, "participant_handles": %s}' % val,
                   key=pf.new_key())
    err(r, 400, "malformed_request")


@L("R-79")
def test_split_unknown_handle_creates_nothing():
    w = split_world()
    err(split(w.ada, 30, ["bob", "cy", "ghost"]), 404, "not_found")
    assert w.bob.requests() == [] and w.cy.requests() == [] and w.ada.requests() == []


@L("R-80")
def test_caller_only_split():
    w = split_world()
    s = ok(split(w.dee, 500, ["dee"]), 201)
    assert s["shares"] == [{"handle": "dee", "amount": 500}] and s["requests"] == []
    assert w.dee.requests() == []


@L("R-80")
def test_split_checks_no_balance():
    w = split_world()
    s = ok(split(w.dee, 1_000_000_000, ["dee", "fay"]), 201)
    assert [q["amount"] for q in s["requests"]] == [500_000_000]
    assert w.dee.balance() == 0 and w.fay.balance() == 0


@L("R-82", "D-06")
def test_zero_share_creates_request():
    w = split_world()
    s = ok(split(w.ada, 1, ["bob", "cy", "dee"]), 201)
    assert [(q["payer_handle"], q["amount"], q["status"]) for q in s["requests"]] == \
        [("bob", 1, "pending"), ("cy", 0, "pending"), ("dee", 0, "pending")]
    zero = [q for q in w.cy.requests() if q["request_id"] == s["requests"][1]["request_id"]]
    assert zero and zero[0]["amount"] == 0
    # D-06: a 0 request is legal; paying it moves nothing and never 5xx
    r = w.cy.pay_request(zero[0]["request_id"])
    assert r.status_code in (201, 409, 422), r.text
    assert pf.total_balance(w) == w.total


@L("R-83")
def test_order_changes_who_gets_extra_unit():
    w = split_world()
    a = ok(split(w.ada, 10, ["bob", "cy", "dee"]), 201)
    b = ok(split(w.ada, 10, ["dee", "cy", "bob"]), 201)
    c = ok(split(w.ada, 10, ["bob", "cy", "dee"]), 201)
    assert {x["handle"]: x["amount"] for x in a["shares"]}["bob"] == 4
    assert {x["handle"]: x["amount"] for x in b["shares"]}["dee"] == 4
    assert {x["handle"]: x["amount"] for x in b["shares"]}["bob"] == 3
    assert [x["amount"] for x in c["shares"]] == [4, 3, 3]   # independent of history


@L("R-83", "I-01")
def test_paid_splits_conserve_money():
    w = split_world()
    ok(w.ada.pay("dee", 1000), 201)
    ok(w.ada.pay("eve", 1000), 201)
    for amount, hs in [(1000, ["bob", "cy", "dee"]), (7, ["dee", "eve", "bob"]),
                       (999, ["eve", "bob", "dee"])]:
        s = ok(split(w.ada, amount, hs), 201)
        for q in s["requests"]:
            if q["amount"] > 0:
                ok(w.users[q["payer_handle"]].pay_request(q["request_id"]), 201)
    assert pf.total_balance(w) == w.total
    assert w.ada.balance() == 10000 - 2000 + 1000 + 7 + 999


@L("R-41", "R-44", "R-45", "R-46", "R-51")
def test_split_idempotency():
    w = split_world()
    err(w.ada.post("/splits", {"amount": 9, "participant_handles": ["bob"]}), 400,
        "missing_idempotency_key")
    k = pf.new_key()
    s = ok(split(w.ada, 9, ["bob", "cy"], key=k), 201)
    assert ok(split(w.ada, 9, ["bob", "cy"], key=k), 200) == s
    err(split(w.ada, 9, ["cy", "bob"], key=k), 409, "idempotency_key_reuse")
    err(split(w.ada, 0, ["bob"], key=k), 409, "idempotency_key_reuse")
    assert len(w.bob.requests()) == 1 and len(w.cy.requests()) == 1
    # replay after one of its requests was cancelled still returns the original
    ok(w.ada.post(f"/requests/{s['requests'][0]['request_id']}/cancel", {}))
    assert ok(split(w.ada, 9, ["bob", "cy"], key=k), 200) == s
