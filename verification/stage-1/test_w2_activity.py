"""W2: activity feed (R-73, R-74, S-10, S-11)."""
import time

import pytest

import pf
from pf import err, ok

L = pytest.mark.ledger


def ids(api):
    return {p["payment_id"] for p in api.activity()}


@L("R-73")
def test_activity_shape():
    w = pf.world()
    b = ok(w.ada.get("/activity"))
    assert set(b) >= {"payments", "has_more"} and b["has_more"] is False
    for p in b["payments"]:
        pf.check_payment(p)


@L("R-74", "S-11")
def test_feed_contract_seeded():
    w = pf.world()
    assert ids(w.ada) == {"p_1"}
    assert ids(w.bob) == {"p_1", "p_2"}
    assert ids(w.cy) == {"p_1", "p_2"}
    assert ids(w.dee) == {"p_1"}


@L("R-74", "S-11")
def test_feed_contract_new_payments():
    w = pf.world()
    pub = ok(w.cy.pay("dee", 5), 201)["payment_id"]
    priv = ok(w.cy.pay("dee", 6, visibility="private"), 201)["payment_id"]
    q = ok(w.ada.ask("bob", 7), 201)
    rpriv = ok(w.bob.pay_request(q["request_id"], {"visibility": "private"}), 201)
    assert pub in ids(w.ada) and pub in ids(w.bob)
    assert priv in ids(w.cy) and priv in ids(w.dee)          # receiver sees private
    assert priv not in ids(w.ada) and priv not in ids(w.bob)
    rp = rpriv["payment_id"]
    assert rp in ids(w.ada) and rp in ids(w.bob)
    assert rp not in ids(w.cy) and rp not in ids(w.dee)
    # identical representation for every viewer
    for a in (w.cy, w.dee, w.ada, w.bob):
        got = [p for p in a.activity() if p["payment_id"] == pub]
        assert got and got[0]["visibility"] == "public"


@L("R-74")
def test_requests_never_in_activity():
    w = pf.world()
    before = {h: ids(a) for h, a in w.users.items()}
    q = ok(w.ada.ask("bob", 10), 201)
    ok(w.bob.post(f"/requests/{q['request_id']}/decline", {}))
    ok(w.ada.ask("cy", 10), 201)
    after = {h: ids(a) for h, a in w.users.items()}
    assert before == after
    for a in w.users.values():
        for p in a.activity():
            assert "payment_id" in p and "status" not in p


@L("R-73")
def test_activity_items_equal_payment_response():
    w = pf.world()
    p = ok(w.ada.pay("bob", 33, note="same"), 201)
    for a in (w.ada, w.bob, w.cy):
        got = [x for x in a.activity() if x["payment_id"] == p["payment_id"]]
        assert got == [p]


@L("R-73")
def test_activity_newest_first():
    w = pf.world()
    made = []
    for i in range(3):
        time.sleep(1.1)
        made.append(ok(w.ada.pay("bob", 1 + i), 201)["payment_id"])
    got = [p["payment_id"] for p in w.bob.activity()]
    assert got[:3] == made[::-1] and set(got[3:]) == {"p_1", "p_2"}, got


@L("R-73", "S-10")
def test_activity_pagination_boundaries():
    w = pf.world(pf.fixture(payments=[]))
    for i in range(6):
        ok(w.ada.pay("bob", 1), 201)
    full = ok(w.bob.get("/activity?limit=200"))
    assert len(full["payments"]) == 6 and full["has_more"] is False
    for limit, offset, n, more in [(6, 0, 6, False), (5, 0, 5, True), (3, 3, 3, False),
                                   (3, 2, 3, True), (1, 5, 1, False), (4, 6, 0, False),
                                   (4, 60, 0, False)]:
        b = ok(w.bob.get(f"/activity?limit={limit}&offset={offset}"))
        assert len(b["payments"]) == n, (limit, offset)
        assert b["has_more"] is more, (limit, offset, b["has_more"])


@L("R-73")
def test_activity_default_limit_50():
    w = pf.world(pf.fixture(payments=[]))
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(10) as ex:
        list(ex.map(lambda i: ok(w.ada.pay("bob", 1), 201), range(51)))
    b = ok(w.dee.get("/activity"))
    assert len(b["payments"]) == 50 and b["has_more"] is True
    b = ok(w.dee.get("/activity?offset=50"))
    assert len(b["payments"]) == 1 and b["has_more"] is False
    err(w.dee.get("/activity?limit=201"), 422, "validation_failed")
