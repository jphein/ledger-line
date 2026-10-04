"""W2: idempotency on payments, requests and pay (R-41..R-51, S-06, S-07, S-08)."""
import pytest

import pf
from pf import err, ok

L = pytest.mark.ledger


@L("R-41", "R-23")
def test_w2_paths_require_key():
    w = pf.world()
    err(w.ada.post("/payments", {"to_handle": "bob", "amount": 1}), 400,
        "missing_idempotency_key")
    err(w.ada.post("/requests", {"payer_handle": "bob", "amount": 1}), 400,
        "missing_idempotency_key")
    err(w.ada.post("/requests/rq_1/pay", {}), 400, "missing_idempotency_key")
    assert w.ada.balance() == 10000


@L("R-44", "R-45")
@pytest.mark.parametrize("kind", ["payment", "request", "pay"])
def test_replay_200_identical(kind):
    w = pf.world()
    k = pf.new_key()
    if kind == "payment":
        call = lambda: w.ada.pay("bob", 250, key=k, note="x")  # noqa: E731
    elif kind == "request":
        call = lambda: w.ada.ask("bob", 250, key=k)  # noqa: E731
    else:
        call = lambda: w.ada.pay_request("rq_1", {"visibility": "public"}, key=k)  # noqa: E731
    first = call()
    assert first.status_code == 201, first.text
    for _ in range(3):
        again = call()
        assert again.status_code == 200, again.text
        assert again.json() == first.json()
    if kind == "payment":
        assert w.ada.balance() == 9750 and w.bob.balance() == 2750
        assert sum(1 for p in w.bob.activity() if p["amount"] == 250) == 1
    elif kind == "request":
        assert len(w.bob.requests("direction=incoming")) == 1
    else:
        assert w.ada.balance() == 8800


@L("R-42")
def test_key_scoped_per_user():
    w = pf.world()
    k = "shared-key"
    a = ok(w.ada.pay("cy", 10, key=k), 201)
    b = ok(w.bob.pay("cy", 10, key=k), 201)
    assert a["payment_id"] != b["payment_id"] and b["from_user_id"] == "u_bob"
    # different body under the same key by another user is still a first use
    c = ok(w.dee.ask("ada", 10, key=k), 201)
    assert c["requester_id"] == "u_dee"
    assert w.cy.balance() == 520


@L("R-43", "S-07")
def test_same_key_same_body_other_path_is_new():
    w = pf.world()
    q1 = ok(w.bob.ask("ada", 10), 201)["request_id"]
    q2 = ok(w.bob.ask("ada", 20), 201)["request_id"]
    k = pf.new_key()
    p1 = ok(w.ada.pay_request(q1, {}, key=k), 201)
    p2 = ok(w.ada.pay_request(q2, {}, key=k), 201)
    assert p1["payment_id"] != p2["payment_id"]
    assert w.ada.balance() == 10000 - 30


@L("R-43", "S-07")
def test_same_key_across_payments_and_requests():
    w = pf.world()
    k = pf.new_key()
    ok(w.ada.pay("bob", 10, key=k), 201)
    ok(w.ada.post("/requests", {"to_handle": "bob", "payer_handle": "bob", "amount": 10},
                  key=k), 201)
    # identical bodies on two paths: /payments and /requests both ignore the other's field
    body = {"to_handle": "cy", "payer_handle": "cy", "amount": 5}
    k2 = pf.new_key()
    ok(w.ada.post("/payments", body, key=k2), 201)
    ok(w.ada.post("/requests", body, key=k2), 201)
    assert w.ada.balance() == 10000 - 15


@L("R-46")
def test_different_body_409_no_effect():
    w = pf.world()
    k = pf.new_key()
    p = ok(w.ada.pay("bob", 100, key=k), 201)
    err(w.ada.pay("bob", 101, key=k), 409, "idempotency_key_reuse")
    err(w.ada.pay("cy", 100, key=k), 409, "idempotency_key_reuse")
    err(w.ada.pay("bob", 100, key=k, note="different"), 409, "idempotency_key_reuse")
    err(w.ada.pay("bob", 100, key=k, visibility="public"), 409, "idempotency_key_reuse")
    assert w.ada.balance() == 9900 and w.cy.balance() == 500
    assert ok(w.ada.pay("bob", 100, key=k), 200) == p


@L("R-47", "S-08")
@pytest.mark.parametrize("failure", ["insufficient", "validation", "not_found", "self",
                                     "malformed"])
def test_key_reusable_after_4xx(failure):
    w = pf.world()
    k = pf.new_key()
    if failure == "insufficient":
        err(w.cy.pay("bob", 100000, key=k), 409, "insufficient_funds")
    elif failure == "validation":
        err(w.cy.pay("bob", 0, key=k), 422)
    elif failure == "not_found":
        err(w.cy.pay("ghost", 10, key=k), 404)
    elif failure == "self":
        err(w.cy.pay("cy", 10, key=k), 422, "self_payment")
    else:
        err(w.cy.post("/payments", raw="{nope", key=k), 400, "malformed_request")
    p = w.cy.pay("bob", 10, key=k)
    assert p.status_code == 201, p.text
    assert ok(w.cy.pay("bob", 10, key=k), 200) == p.json()
    assert w.cy.balance() == 490


@L("R-47")
def test_same_failing_body_retried_after_state_change():
    """The same body that failed for funds succeeds as a first use once funded."""
    w = pf.world()
    k = pf.new_key()
    err(w.dee.pay("ada", 50, key=k), 409, "insufficient_funds")
    ok(w.ada.pay("dee", 50), 201)
    ok(w.dee.pay("ada", 50, key=k), 201)
    assert w.dee.balance() == 0


@L("R-48")
def test_key_order_and_whitespace_irrelevant():
    w = pf.world()
    k = pf.new_key()
    a = w.ada.post("/payments", raw='{"to_handle":"bob","amount":10,"note":"n"}', key=k)
    assert a.status_code == 201
    b = w.ada.post("/payments", raw='{\n  "note" : "n",\n\t"amount":10 , "to_handle":"bob"}',
                   key=k)
    assert b.status_code == 200 and b.json() == a.json()
    assert w.ada.balance() == 9990


@L("R-48")
def test_numerically_equal_amount_is_same_body():
    w = pf.world()
    k = pf.new_key()
    a = w.ada.post("/payments", raw='{"to_handle":"bob","amount":1000}', key=k)
    assert a.status_code == 201
    b = w.ada.post("/payments", raw='{"to_handle":"bob","amount":1000.0}', key=k)
    assert b.status_code == 200 and b.json() == a.json(), b.text
    assert w.ada.balance() == 9000


@L("R-48", "R-46")
def test_unicode_escape_same_value():
    w = pf.world()
    k = pf.new_key()
    a = w.ada.post("/payments", raw='{"to_handle":"bob","amount":5,"note":"é"}', key=k)
    assert a.status_code == 201
    b = w.ada.post("/payments", raw='{"to_handle":"bob","amount":5,"note":"\\u00e9"}', key=k)
    assert b.status_code == 200 and b.json() == a.json()
    c = w.ada.post("/payments", raw='{"to_handle":"bob","amount":5,"note":"e\\u0301"}', key=k)
    err(c, 409, "idempotency_key_reuse")


@L("R-50", "S-06")
def test_replay_after_request_cancelled_returns_original():
    w = pf.world()
    k = pf.new_key()
    q = ok(w.bob.ask("ada", 10, key=k), 201)
    ok(w.bob.post(f"/requests/{q['request_id']}/cancel", {}))
    again = ok(w.bob.ask("ada", 10, key=k), 200)
    assert again == q and again["status"] == "pending"
    assert len(w.bob.requests("direction=outgoing")) == 1


@L("R-50", "S-06")
def test_replay_after_request_paid_returns_original():
    w = pf.world()
    k = pf.new_key()
    q = ok(w.bob.ask("ada", 10, key=k), 201)
    ok(w.ada.pay_request(q["request_id"]), 201)
    assert ok(w.bob.ask("ada", 10, key=k), 200) == q


@L("R-50")
def test_payment_replay_after_funds_gone():
    w = pf.world()
    k = pf.new_key()
    p = ok(w.cy.pay("bob", 500, key=k), 201)
    assert w.cy.balance() == 0
    assert ok(w.cy.pay("bob", 500, key=k), 200) == p
    assert w.cy.balance() == 0 and w.bob.balance() == 3000


@L("R-51")
def test_claimed_key_beats_validation():
    w = pf.world()
    k = pf.new_key()
    ok(w.ada.pay("bob", 10, key=k), 201)
    err(w.ada.pay("bob", -1, key=k), 409, "idempotency_key_reuse")
    err(w.ada.pay("bob", "ten", key=k), 409, "idempotency_key_reuse")
    err(w.ada.pay("ghost", 10, key=k), 409, "idempotency_key_reuse")
    err(w.ada.pay("ada", 10, key=k), 409, "idempotency_key_reuse")
    err(w.ada.post("/payments", {"amount": 10}, key=k), 409, "idempotency_key_reuse")
    err(w.ada.pay("bob", 10, key=k, note=None), 409, "idempotency_key_reuse")
    err(w.ada.pay("bob", 10**12, key=k), 409, "idempotency_key_reuse")
    assert w.ada.balance() == 9990


@L("R-51")
def test_claimed_pay_key_beats_resource_checks():
    w = pf.world()
    q = ok(w.bob.ask("ada", 10), 201)
    k = pf.new_key()
    ok(w.ada.pay_request(q["request_id"], {}, key=k), 201)
    err(w.ada.pay_request(q["request_id"], {"visibility": "nope"}, key=k), 409,
        "idempotency_key_reuse")
    err(w.ada.pay_request(q["request_id"], {"visibility": "private"}, key=k), 409,
        "idempotency_key_reuse")


@L("R-51", "R-43")
def test_claimed_key_on_other_path_is_not_claimed():
    w = pf.world()
    k = pf.new_key()
    ok(w.ada.pay("bob", 10, key=k), 201)
    # same key on /requests with an invalid body: not a replay, so ordinary validation
    err(w.ada.post("/requests", {"payer_handle": "bob", "amount": -1}, key=k), 422,
        "validation_failed")


@L("R-45", "R-53")
def test_replay_response_has_same_headers_class():
    w = pf.world()
    k = pf.new_key()
    a = w.ada.pay("bob", 10, key=k)
    b = w.ada.pay("bob", 10, key=k)
    assert a.status_code == 201 and b.status_code == 200
    assert b.headers["content-type"].replace(" ", "").lower() == \
        "application/json;charset=utf-8"
