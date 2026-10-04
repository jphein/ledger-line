"""W2: requests, pay/decline/cancel, listing (R-63..R-72, R-75, S-09, S-10, D-04, D-05)."""
import time

import pytest

import pf
from pf import Api, err, ok

L = pytest.mark.ledger


@L("R-63")
def test_request_201_shape():
    w = pf.world()
    q = ok(w.bob.ask("ada", 1200, note="taxi"), 201)
    pf.check_request(q, requester_id="u_bob", requester_handle="bob", payer_id="u_ada",
                     payer_handle="ada", amount=1200, currency="EUR", note="taxi",
                     status="pending", payment_id=None)
    q2 = ok(w.bob.ask("ada", 5), 201)
    assert q2["note"] == "" and q2["request_id"] != q["request_id"]
    assert w.bob.balance() == 2500 and w.ada.balance() == 10000


@L("R-64")
@pytest.mark.parametrize("amount", [0, -5, 1_000_000_001, 2.5])
def test_request_amount_422(amount):
    w = pf.world()
    err(w.bob.ask("ada", amount), 422, "validation_failed")


@L("R-64")
def test_request_errors():
    w = pf.world()
    ok(w.bob.ask("ada", 1_000_000_000), 201)
    ok(w.bob.ask("ada", 1), 201)
    err(w.bob.ask("bob", 10), 422, "self_request")
    err(w.bob.ask("ada", 10, note="n" * 201), 422, "validation_failed")
    ok(w.bob.ask("ada", 10, note="n" * 200), 201)
    err(w.bob.ask("ghost", 10), 404, "not_found")
    assert len(w.bob.requests("direction=outgoing")) == 3


@L("R-65")
def test_request_exceeding_balance_is_fine():
    w = pf.world()
    q = ok(w.ada.ask("dee", 1_000_000_000), 201)
    assert q["status"] == "pending"
    assert [x["request_id"] for x in w.dee.requests()] == [q["request_id"]]


@L("R-66", "R-53")
def test_pay_request_201():
    w = pf.world()
    q = ok(w.bob.ask("ada", 700, note="tickets"), 201)
    p = ok(w.ada.pay_request(q["request_id"], {"visibility": "private"}), 201)
    pf.check_payment(p, from_user_id="u_ada", from_handle="ada", to_user_id="u_bob",
                     to_handle="bob", amount=700, currency="EUR", visibility="private",
                     request_id=q["request_id"], settlement_id=None)
    assert p["note"] in ("tickets", ""), "note of a request payment"
    assert w.ada.balance() == 9300 and w.bob.balance() == 3200
    for a in (w.ada, w.bob):
        got = [x for x in a.requests() if x["request_id"] == q["request_id"]][0]
        assert got["status"] == "paid" and got["payment_id"] == p["payment_id"]
    assert any(x["payment_id"] == p["payment_id"] for x in w.bob.activity())


@L("R-66", "R-54")
def test_pay_request_default_public():
    w = pf.world()
    q = ok(w.bob.ask("ada", 10), 201)
    p = ok(w.ada.pay_request(q["request_id"], {}), 201)
    assert p["visibility"] == "public"
    assert any(x["payment_id"] == p["payment_id"] for x in w.dee.activity())


@L("R-67", "R-46")
def test_pay_empty_vs_explicit_public_are_different_bodies():
    w = pf.world()
    q = ok(w.bob.ask("ada", 10), 201)
    k = pf.new_key()
    p = ok(w.ada.pay_request(q["request_id"], {}, key=k), 201)
    err(w.ada.pay_request(q["request_id"], {"visibility": "public"}, key=k), 409,
        "idempotency_key_reuse")
    assert ok(w.ada.pay_request(q["request_id"], {}, key=k), 200) == p
    assert w.ada.balance() == 9990


@L("R-68")
def test_pay_not_pending_409():
    w = pf.world()
    err(w.cy.pay_request("rq_2"), 409, "request_not_pending")  # seeded declined
    q = ok(w.bob.ask("ada", 10), 201)
    ok(w.ada.pay_request(q["request_id"]), 201)
    err(w.ada.pay_request(q["request_id"]), 409, "request_not_pending")  # new key
    c = ok(w.bob.ask("ada", 10), 201)
    ok(w.bob.post(f"/requests/{c['request_id']}/cancel", {}))
    err(w.ada.pay_request(c["request_id"]), 409, "request_not_pending")
    assert w.ada.balance() == 9990


@L("R-68", "S-09", "R-47")
def test_insufficient_then_funded_same_request_pays():
    w = pf.world()
    q = ok(w.ada.ask("dee", 300), 201)
    k = pf.new_key()
    err(w.dee.pay_request(q["request_id"], key=k), 409, "insufficient_funds")
    got = [x for x in w.dee.requests() if x["request_id"] == q["request_id"]][0]
    assert got["status"] == "pending" and got["payment_id"] is None
    assert w.dee.balance() == 0 and w.ada.balance() == 10000
    ok(w.bob.pay("dee", 299), 201)
    err(w.dee.pay_request(q["request_id"], key=k), 409, "insufficient_funds")
    ok(w.cy.pay("dee", 1), 201)
    p = ok(w.dee.pay_request(q["request_id"], key=k), 201)  # same key: first use again
    assert p["amount"] == 300 and w.dee.balance() == 0 and w.ada.balance() == 10300


@L("R-68", "D-05")
def test_pay_wrong_caller_403():
    w = pf.world()
    q = ok(w.bob.ask("ada", 10), 201)
    err(w.bob.pay_request(q["request_id"]), 403, "forbidden")   # requester
    err(w.cy.pay_request(q["request_id"]), 403, "forbidden")    # third party
    assert w.bob.balance() == 2500 and w.cy.balance() == 500
    got = [x for x in w.ada.requests() if x["request_id"] == q["request_id"]][0]
    assert got["status"] == "pending"


@L("R-68", "D-04")
def test_pay_unknown_404_and_order():
    w = pf.world()
    err(w.ada.pay_request("rq_does_not_exist"), 404, "not_found")
    err(w.ada.pay_request("x" * 64), 404, "not_found")
    # D-04: role before status — requester paying a declined request gets 403
    err(w.ada.pay_request("rq_2"), 403, "forbidden")
    # D-04: status before funds — payer short on a declined request gets 409 not_pending
    q = ok(w.ada.ask("dee", 50), 201)
    ok(w.dee.post(f"/requests/{q['request_id']}/decline", {}))
    err(w.dee.pay_request(q["request_id"]), 409, "request_not_pending")


@L("R-69", "R-45", "R-50")
def test_replay_paid_request_returns_original():
    w = pf.world()
    q = ok(w.bob.ask("ada", 400), 201)
    k = pf.new_key()
    p = ok(w.ada.pay_request(q["request_id"], {"visibility": "private"}, key=k), 201)
    for _ in range(3):
        assert ok(w.ada.pay_request(q["request_id"], {"visibility": "private"}, key=k),
                  200) == p
    assert w.ada.balance() == 9600 and w.bob.balance() == 2900
    assert sum(1 for x in w.ada.activity() if x.get("request_id") == q["request_id"]) == 1


# ------------------------------------------------------------- decline / cancel

@L("R-70")
def test_decline_flow():
    w = pf.world()
    q = ok(w.bob.ask("ada", 10), 201)
    path = f"/requests/{q['request_id']}/decline"
    d = ok(w.ada.post(path, {}))
    pf.check_request(d, request_id=q["request_id"], status="declined", payment_id=None,
                     requester_id="u_bob", payer_id="u_ada", amount=10)
    assert ok(w.ada.post(path, {})) == d                 # twice: 200 current state
    err(w.bob.post(path, {}), 403, "forbidden")          # requester
    err(w.cy.post(path, {}), 403, "forbidden")           # third party
    err(w.ada.post("/requests/nope/decline", {}), 404, "not_found")
    err(w.bob.post(f"/requests/{q['request_id']}/cancel", {}), 409, "request_not_pending")


@L("R-70")
def test_decline_paid_or_cancelled_409():
    w = pf.world()
    a = ok(w.bob.ask("ada", 10), 201)
    ok(w.ada.pay_request(a["request_id"]), 201)
    err(w.ada.post(f"/requests/{a['request_id']}/decline", {}), 409, "request_not_pending")
    b = ok(w.bob.ask("ada", 10), 201)
    ok(w.bob.post(f"/requests/{b['request_id']}/cancel", {}))
    err(w.ada.post(f"/requests/{b['request_id']}/decline", {}), 409, "request_not_pending")


@L("R-71")
def test_cancel_flow():
    w = pf.world()
    q = ok(w.bob.ask("ada", 10), 201)
    path = f"/requests/{q['request_id']}/cancel"
    c = ok(w.bob.post(path, {}))
    pf.check_request(c, request_id=q["request_id"], status="cancelled", payment_id=None)
    assert ok(w.bob.post(path, {})) == c
    err(w.ada.post(path, {}), 403, "forbidden")          # payer
    err(w.cy.post(path, {}), 403, "forbidden")           # third party
    err(w.bob.post("/requests/nope/cancel", {}), 404, "not_found")


@L("R-71")
def test_cancel_paid_or_declined_409():
    w = pf.world()
    a = ok(w.bob.ask("ada", 10), 201)
    ok(w.ada.pay_request(a["request_id"]), 201)
    err(w.bob.post(f"/requests/{a['request_id']}/cancel", {}), 409, "request_not_pending")
    err(w.ada.post("/requests/rq_2/cancel", {}), 409, "request_not_pending")  # seeded declined


@L("R-70", "R-71")
def test_decline_cancel_without_body():
    """No body is specified for decline/cancel; an empty body must work."""
    w = pf.world()
    a = ok(w.bob.ask("ada", 10), 201)
    r = w.ada.request("POST", f"/requests/{a['request_id']}/decline")
    assert ok(r)["status"] == "declined"
    b = ok(w.bob.ask("ada", 10), 201)
    r = w.bob.request("POST", f"/requests/{b['request_id']}/cancel")
    assert ok(r)["status"] == "cancelled"


@L("R-70", "R-71", "R-09")
def test_decline_cancel_ignore_body_and_key():
    w = pf.world()
    a = ok(w.bob.ask("ada", 10), 201)
    assert ok(w.ada.post(f"/requests/{a['request_id']}/decline", {"x": 1},
                         key="whatever"))["status"] == "declined"


# ------------------------------------------------------------------ listing

@L("R-72", "R-75")
def test_list_only_own_requests():
    w = pf.world()
    q = ok(w.bob.ask("cy", 10), 201)
    assert q["request_id"] not in [x["request_id"] for x in w.ada.requests()]
    assert q["request_id"] not in [x["request_id"] for x in w.dee.requests()]
    assert w.dee.requests() == []
    assert q["request_id"] in [x["request_id"] for x in w.cy.requests()]


@L("R-72")
def test_list_filters():
    w = pf.world()
    out_p = ok(w.ada.ask("bob", 1), 201)                         # ada outgoing pending
    in_p = ok(w.bob.ask("ada", 2), 201)                          # ada incoming pending
    in_d = ok(w.cy.ask("ada", 3), 201)
    ok(w.ada.post(f"/requests/{in_d['request_id']}/decline", {}))
    out_c = ok(w.ada.ask("cy", 4), 201)
    ok(w.ada.post(f"/requests/{out_c['request_id']}/cancel", {}))
    in_paid = ok(w.cy.ask("ada", 5), 201)
    ok(w.ada.pay_request(in_paid["request_id"]), 201)

    def ids(q):
        return {x["request_id"] for x in w.ada.requests(q)}
    every = {out_p, in_p, in_d, out_c, in_paid}
    every_ids = {x["request_id"] for x in every} | {"rq_1", "rq_2"}
    assert ids("") == every_ids
    assert ids("direction=outgoing") == {out_p["request_id"], out_c["request_id"], "rq_2"}
    assert ids("direction=incoming") == {in_p["request_id"], in_d["request_id"],
                                         in_paid["request_id"], "rq_1"}
    assert ids("status=pending") == {out_p["request_id"], in_p["request_id"], "rq_1"}
    assert ids("status=declined") == {in_d["request_id"], "rq_2"}
    assert ids("status=cancelled") == {out_c["request_id"]}
    assert ids("status=paid") == {in_paid["request_id"]}
    assert ids("direction=incoming&status=pending") == {in_p["request_id"], "rq_1"}
    assert ids("direction=outgoing&status=declined") == {"rq_2"}
    for x in w.ada.requests("direction=incoming"):
        assert x["payer_id"] == "u_ada"
    for x in w.ada.requests("direction=outgoing"):
        assert x["requester_id"] == "u_ada"


@L("R-72")
@pytest.mark.parametrize("q", ["direction=sideways", "direction=Incoming", "direction=",
                               "status=open", "status=PAID", "status=", "status=paid,pending"])
def test_list_unknown_enum_422(q):
    w = pf.world()
    err(w.ada.get(f"/requests?{q}"), 422, "validation_failed")


@L("R-72")
def test_list_newest_first():
    w = pf.world()
    made = []
    for i in range(3):
        made.append(ok(w.bob.ask("ada", 10 + i), 201)["request_id"])
        time.sleep(1.1)
    got = [x["request_id"] for x in w.ada.requests()]
    assert got[:3] == made[::-1], got
    stamps = [x["created_at"] for x in ok(w.ada.get("/requests"))["requests"]]
    assert len(stamps) == 5


@L("R-72", "S-10")
def test_list_pagination_boundaries():
    w = pf.world(pf.fixture(requests=[]))
    for i in range(5):
        ok(w.bob.ask("ada", i + 1), 201)
    full = ok(w.ada.get("/requests"))
    assert len(full["requests"]) == 5 and full["has_more"] is False
    all_ids = [x["request_id"] for x in full["requests"]]
    cases = [(5, 0, 5, False), (4, 0, 4, True), (2, 3, 2, False), (2, 2, 2, True),
             (1, 4, 1, False), (3, 5, 0, False), (200, 0, 5, False), (1, 0, 1, True),
             (10, 100, 0, False)]
    for limit, offset, n, more in cases:
        b = ok(w.ada.get(f"/requests?limit={limit}&offset={offset}"))
        assert len(b["requests"]) == n, (limit, offset, b)
        assert b["has_more"] is more, (limit, offset, b["has_more"])
        assert [x["request_id"] for x in b["requests"]] == all_ids[offset:offset + limit]


@L("R-72")
def test_list_default_limit_50():
    w = pf.world(pf.fixture(requests=[]))
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(10) as ex:
        list(ex.map(lambda i: ok(w.bob.ask("ada", 1), 201), range(52)))
    b = ok(w.ada.get("/requests"))
    assert len(b["requests"]) == 50 and b["has_more"] is True
    b = ok(w.ada.get("/requests?offset=50"))
    assert len(b["requests"]) == 2 and b["has_more"] is False
