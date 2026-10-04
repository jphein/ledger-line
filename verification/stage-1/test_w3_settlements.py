"""W3: settlements (R-92..R-101, S-11, S-18, D-08)."""
import pytest

import pf
from pf import Api, err, ok

L = pytest.mark.ledger


def sw():
    return pf.world(pf.fixture(users=[pf.ADA, pf.BOB, pf.CY, pf.DEE, pf.OP],
                               operators=["u_op"]))


def t(f, to, amount, **extra):
    return {"from_handle": f, "to_handle": to, "amount": amount, **extra}


def settle(api, transfers, key=None):
    return api.post("/settlements", {"transfers": transfers}, key=key or pf.new_key())


def balances(w):
    return {h: a.balance() for h, a in w.users.items()}


@L("R-92")
def test_auth_and_operator_gate():
    w = sw()
    body = [t("ada", "bob", 1)]
    err(Api().post("/settlements", {"transfers": body}, key=pf.new_key()), 401,
        "unauthenticated")
    err(settle(w.ada, body), 403, "forbidden")
    err(settle(w.bob, [t("bob", "cy", 1)]), 403, "forbidden")
    err(w.ada.post("/settlements", {"transfers": body}), 403, "forbidden")  # D-02 order
    err(w.op.post("/settlements", {"transfers": body}), 400, "missing_idempotency_key")
    err(w.op.post("/settlements", {"transfers": body}, key="k" * 256), 422,
        "validation_failed")
    assert balances(w)["ada"] == 10000


@L("R-93", "R-98", "R-54")
def test_single_transfer_defaults_and_shape():
    w = sw()
    r = ok(settle(w.op, [t("ada", "bob", 100)]), 201)
    assert set(r) >= {"settlement_id", "committed_at", "payments"}
    pf.check_id(r["settlement_id"])
    pf.check_ts(r["committed_at"])
    assert len(r["payments"]) == 1
    pf.check_payment(r["payments"][0], from_user_id="u_ada", from_handle="ada",
                     to_user_id="u_bob", to_handle="bob", amount=100, note="",
                     visibility="public", request_id=None, currency="EUR",
                     settlement_id=r["settlement_id"], created_at=r["committed_at"])
    b = balances(w)
    assert b["ada"] == 9900 and b["bob"] == 2600 and b["op"] == 0


@L("R-93", "R-98")
def test_32_transfers_in_input_order():
    w = sw()
    hs = ["ada", "bob", "cy", "dee"]
    transfers = [t(hs[i % 4], hs[(i + 1) % 4], i + 1, note=f"n{i}") for i in range(32)]
    r = ok(settle(w.op, transfers), 201)
    assert [(p["from_handle"], p["to_handle"], p["amount"], p["note"])
            for p in r["payments"]] == \
        [(x["from_handle"], x["to_handle"], x["amount"], x["note"]) for x in transfers]
    assert len({p["payment_id"] for p in r["payments"]}) == 32
    assert {p["settlement_id"] for p in r["payments"]} == {r["settlement_id"]}
    assert {p["created_at"] for p in r["payments"]} == {r["committed_at"]}
    assert pf.total_balance(w) == w.total


@L("R-93", "R-94")
@pytest.mark.parametrize("body", [{"transfers": []}, {"transfers": [t("ada", "bob", 1)] * 33},
                                  {}, {"transfers": None}, {"transfers": "x"},
                                  {"transfers": {"from_handle": "ada"}},
                                  {"transfers": [5]}, {"transfers": [[t("ada", "bob", 1)]]},
                                  {"transfers": [t("ada", "bob", 1), "x"]},
                                  {"transfers": [t("ada", "bob", 1), None]}])
def test_bad_batch_shape_422(body):
    w = sw()
    err(w.op.post("/settlements", body, key=pf.new_key()), 422, "validation_failed")
    assert balances(w)["ada"] == 10000


@L("R-93", "R-56", "R-58", "R-59", "R-27")
@pytest.mark.parametrize("entry", [t("ada", "bob", 0), t("ada", "bob", -3),
                                   t("ada", "bob", 1_000_000_001), t("ada", "bob", 1.5),
                                   t("ada", "bob", "1"), t("ada", "bob", True),
                                   t("ada", "bob", 1, note="n" * 201),
                                   t("ada", "bob", 1, note=None),
                                   t("ada", "bob", 1, visibility="secret"),
                                   t("ada", "bob", 1, visibility=None),
                                   {"from_handle": "ada", "to_handle": "bob"}])
def test_entry_rules_422(entry):
    w = sw()
    err(settle(w.op, [t("cy", "dee", 1), entry]), 422, "validation_failed")
    assert balances(w) == {"ada": 10000, "bob": 2500, "cy": 500, "dee": 0, "op": 0}


@L("R-94")
def test_unknown_handle_404_and_self_422():
    w = sw()
    err(settle(w.op, [t("ada", "ghost", 1)]), 404, "not_found")
    err(settle(w.op, [t("ghost", "ada", 1)]), 404, "not_found")
    err(settle(w.op, [t("ada", "ada", 1)]), 422, "self_payment")
    err(settle(w.op, [t("op", "op", 1)]), 422, "self_payment")
    assert balances(w)["ada"] == 10000


@L("R-94", "R-09")
def test_unknown_fields_ignored():
    w = sw()
    r = ok(w.op.post("/settlements", {"transfers": [t("ada", "bob", 2, extra=1,
                                                      settlement_id="x")],
                                      "comment": "hi"}, key=pf.new_key()), 201)
    assert r["payments"][0]["amount"] == 2


@L("R-95", "D-08")
def test_entry_error_order():
    w = sw()
    # an unaffordable first entry loses to a later entry error
    err(settle(w.op, [t("dee", "ada", 10**6), t("ada", "ghost", 1)]), 404, "not_found")
    err(settle(w.op, [t("dee", "ada", 10**6), t("ada", "ada", 1)]), 422, "self_payment")
    # first failing entry in input order wins
    err(settle(w.op, [t("ada", "ada", 1), t("ada", "ghost", 1)]), 422, "self_payment")
    err(settle(w.op, [t("ada", "ghost", 1), t("ada", "ada", 1)]), 404, "not_found")
    err(settle(w.op, [t("ada", "bob", 0), t("ada", "ghost", 1)]), 422, "validation_failed")
    err(settle(w.op, [t("ada", "ghost", 1), t("ada", "bob", 0)]), 404, "not_found")
    assert balances(w)["dee"] == 0


@L("R-96", "S-18")
def test_net_affordability():
    w = sw()
    ok(settle(w.op, [t("ada", "dee", 100), t("dee", "cy", 100)]), 201)
    ok(settle(w.op, [t("dee", "cy", 100), t("ada", "dee", 100)]), 201)  # order irrelevant
    b = balances(w)
    assert b["dee"] == 0 and b["cy"] == 700 and b["ada"] == 9800
    ok(settle(w.op, [t("cy", "dee", 700), t("dee", "bob", 700)]), 201)  # exact to zero
    assert balances(w)["cy"] == 0


@L("R-96", "R-97", "R-61")
def test_collective_insufficient_409_nothing_moves():
    w = sw()
    before = balances(w)
    acts = {h: len(a.activity()) for h, a in w.users.items()}
    err(settle(w.op, [t("ada", "dee", 100), t("dee", "cy", 101)]), 409, "insufficient_funds")
    err(settle(w.op, [t("ada", "bob", 1), t("cy", "bob", 501)]), 409, "insufficient_funds")
    err(settle(w.op, [t("cy", "bob", 300), t("cy", "dee", 201)]), 409, "insufficient_funds")
    assert balances(w) == before
    assert {h: len(a.activity()) for h, a in w.users.items()} == acts


@L("R-97", "R-47")
def test_failed_settlement_claims_no_key():
    w = sw()
    k = pf.new_key()
    err(settle(w.op, [t("ada", "ghost", 1)], key=k), 404)
    err(settle(w.op, [t("cy", "bob", 10**6)], key=k), 409, "insufficient_funds")
    err(settle(w.op, [], key=k), 422)
    r = ok(settle(w.op, [t("ada", "bob", 3)], key=k), 201)
    assert ok(settle(w.op, [t("ada", "bob", 3)], key=k), 200) == r


@L("R-99")
def test_ordinary_payments_have_null_settlement_id():
    w = sw()
    p = ok(w.ada.pay("bob", 1), 201)
    assert "settlement_id" in p and p["settlement_id"] is None
    q = ok(w.bob.ask("ada", 1), 201)
    pp = ok(w.ada.pay_request(q["request_id"]), 201)
    assert pp["settlement_id"] is None
    for x in w.ada.activity():
        assert "settlement_id" in x


@L("R-100", "S-11", "R-74")
def test_member_visibility_and_operator_has_no_extra_access():
    w = sw()
    r = ok(settle(w.op, [t("ada", "bob", 10, visibility="private"),
                         t("bob", "cy", 5, visibility="public")]), 201)
    priv, pub = (p["payment_id"] for p in r["payments"])
    ids = {h: {p["payment_id"] for p in a.activity()} for h, a in w.users.items()}
    assert priv in ids["ada"] and priv in ids["bob"]
    assert priv not in ids["cy"] and priv not in ids["dee"] and priv not in ids["op"]
    assert all(pub in s for s in ids.values())
    assert "p_2" not in ids["op"]                         # seeded private
    assert w.op.requests() == []
    err(w.op.pay_request("rq_1"), 403, "forbidden")
    err(w.op.post("/requests/rq_1/decline", {}), 403, "forbidden")
    err(w.op.post("/requests/rq_1/cancel", {}), 403, "forbidden")


@L("R-101", "R-45", "R-46", "R-50", "R-51")
def test_settlement_replay():
    w = sw()
    k = pf.new_key()
    body = [t("ada", "bob", 40, note="x"), t("bob", "cy", 20)]
    r = ok(settle(w.op, body, key=k), 201)
    after = balances(w)
    for _ in range(3):
        assert ok(settle(w.op, body, key=k), 200) == r
    assert balances(w) == after
    err(settle(w.op, [t("ada", "bob", 41, note="x"), t("bob", "cy", 20)], key=k), 409,
        "idempotency_key_reuse")
    err(settle(w.op, [t("ada", "ghost", 1)], key=k), 409, "idempotency_key_reuse")
    err(settle(w.op, list(reversed(body)), key=k), 409, "idempotency_key_reuse")
    assert balances(w) == after


@L("R-101", "R-42")
def test_settlement_key_scoped_per_operator():
    f = pf.fixture(users=[pf.ADA, pf.BOB, pf.CY, pf.OP, pf.user("u_op2", "op2", 0)],
                   operators=["u_op", "u_op2"])
    w = pf.world(f)
    k = "same"
    a = ok(settle(w.op, [t("ada", "bob", 1)], key=k), 201)
    b = ok(settle(w.op2, [t("ada", "bob", 1)], key=k), 201)
    assert a["settlement_id"] != b["settlement_id"]
    assert w.bob.balance() == 2502
