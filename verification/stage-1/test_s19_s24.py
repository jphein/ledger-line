"""Silent lines added in the final ledger (S-19..S-24) plus auditor probes (R-30, R-46, D-11)."""
import time

import pytest

import pf
from pf import Api, err, ok

L = pytest.mark.ledger


def signup(email, password="12345678"):
    return Api().post("/auth/signup", {"email": email, "password": password,
                                       "display_name": "X"})


@L("S-19", "R-33", "R-37", "D-07")
def test_email_taken_before_handle_taken():
    pf.world()
    err(signup("ada@example.com"), 409, "email_taken")          # handle also taken
    ok(signup("zoe@x.com"), 201)
    err(signup("zoe@x.com"), 409, "email_taken")
    err(signup("Zoe@x.com"), 409, "handle_taken")               # D-07 case-sensitive email


@L("S-20", "R-22")
@pytest.mark.parametrize("lit", ["NaN", "Infinity", "-Infinity", "nan", "inf"])
def test_non_json_constants_400(lit):
    w = pf.world()
    err(w.ada.post("/payments", raw='{"to_handle":"bob","amount":%s}' % lit,
                   key=pf.new_key()), 400, "malformed_request")
    err(w.ada.post("/payments", raw='{"to_handle":"bob","amount":5,"x":%s}' % lit,
                   key=pf.new_key()), 400, "malformed_request")
    assert w.ada.balance() == 10000


@L("S-20", "R-56")
@pytest.mark.parametrize("lit", ["1e400", "-1e400", "1e-400", "1e999999999999"])
def test_huge_or_tiny_amount_422(lit):
    w = pf.world()
    err(w.ada.post("/payments", raw='{"to_handle":"bob","amount":%s}' % lit,
                   key=pf.new_key()), 422, "validation_failed")
    assert w.ada.balance() == 10000


@L("S-20", "R-30")
def test_over_4300_digit_int_400():
    w = pf.world()
    big = "9" * 4301
    err(w.ada.post("/payments", raw='{"to_handle":"bob","amount":%s}' % big,
                   key=pf.new_key()), 400, "malformed_request")
    err(w.ada.post("/payments", raw='{"to_handle":"bob","amount":5,"x":%s}' % big,
                   key=pf.new_key()), 400, "malformed_request")
    err(Api().post("/_test/reset", raw='{"x":%s}' % big), 400, "malformed_request")
    assert w.ada.balance() == 10000


@L("S-21", "R-30", "D-12")
def test_lone_surrogate_note_never_5xx():
    w = pf.world()
    r = w.ada.post("/payments", raw='{"to_handle":"bob","amount":1,"note":"a\\ud800b"}',
                   key=pf.new_key())
    assert r.status_code < 500
    if r.status_code == 201:
        assert r.json()["note"] == "a\ud800b"
        assert any(p["note"] == "a\ud800b" for p in w.bob.activity())
    r = w.ada.post("/requests", raw='{"payer_handle":"bob","amount":1,"note":"\\udfff"}',
                   key=pf.new_key())
    assert r.status_code < 500
    ok(w.bob.get("/requests"))
    ok(Api().get("/_test/export"))


def _bad_fixtures():
    f = pf.fixture

    def mut(fn):
        x = f()
        fn(x)
        return x
    return {
        "missing_users": mut(lambda x: x.pop("users")),
        "users_not_list": mut(lambda x: x.__setitem__("users", {})),
        "balance_str": mut(lambda x: x["users"][0].__setitem__("balance", "10000")),
        "balance_float": mut(lambda x: x["users"][0].__setitem__("balance", 10.5)),
        "balance_bool": mut(lambda x: x["users"][0].__setitem__("balance", True)),
        "bad_handle_upper": mut(lambda x: x["users"][0].__setitem__("handle", "Ada")),
        "bad_handle_long": mut(lambda x: x["users"][0].__setitem__("handle", "a" * 21)),
        "dup_id": mut(lambda x: x["users"][1].__setitem__("id", "u_ada")),
        "dup_handle": mut(lambda x: x["users"][1].__setitem__("handle", "ada")),
        "dup_email": mut(lambda x: x["users"][1].__setitem__("email", "ada@example.com")),
        "payment_unknown_user": mut(lambda x: x["payments"][0].__setitem__("to_user_id", "u_x")),
        "request_unknown_user": mut(lambda x: x["requests"][0].__setitem__("payer_id", "u_x")),
        "minor_units_1": mut(lambda x: x.__setitem__("minor_units", 1)),
        "negative_balance": mut(lambda x: x["users"][2].__setitem__("balance", -1)),
    }


@L("S-22", "R-18", "S-12")
@pytest.mark.parametrize("name", list(_bad_fixtures()))
def test_malformed_fixture_422_changes_nothing(name):
    w = pf.world()
    ok(w.ada.pay("bob", 7), 201)
    err(Api().post("/_test/reset", _bad_fixtures()[name]), 422, "validation_failed")
    assert w.ada.balance() == 9993 and w.bob.balance() == 2507


@L("S-22")
@pytest.mark.parametrize("raw", ["[]", "\"x\"", "5", "null", "{", ""])
def test_non_object_reset_and_import_400(raw):
    w = pf.world()
    ok(w.ada.pay("bob", 7), 201)
    err(Api().post("/_test/reset", raw=raw), 400, "malformed_request")
    r = Api().post("/_test/import", raw=raw)
    err(r, 400, "malformed_request")
    assert w.ada.balance() == 9993


@L("S-23", "R-06", "R-05")
def test_1000_user_reset_under_10s():
    users = [pf.user(f"u_{i}", f"k{i}", i) for i in range(1000)]
    fix = pf.fixture(users=users, payments=[], requests=[])
    t0 = time.monotonic()
    r = Api().post("/_test/reset", fix, budget=10.0)
    el = time.monotonic() - t0
    assert r.status_code == 204, r.text
    assert el < 10.0, f"reset took {el:.2f}s"
    print(f"S-23 1000-user reset {el:.2f}s")
    assert pf.login("k999@example.com").balance() == 999
    assert pf.login("k0@example.com").balance() == 0


@L("S-24", "R-79", "R-05")
def test_split_with_1000_unknown_handles():
    w = pf.world()
    hs = [f"ghost{i}" for i in range(1000)]
    t0 = time.monotonic()
    r = w.ada.post("/splits", {"amount": 1000, "participant_handles": hs}, key=pf.new_key())
    assert time.monotonic() - t0 < 5.0
    assert r.status_code in (404, 422), r.text
    assert w.ada.requests() and len(w.ada.requests()) == 2   # only the seeded ones


@L("R-30", "R-09", "R-45")
def test_unknown_field_huge_exponent_201_then_replay():
    w = pf.world()
    k = pf.new_key()
    body = '{"to_handle":"bob","amount":100,"x":1e999999999999}'
    a = w.ada.post("/payments", raw=body, key=k)
    assert a.status_code == 201, a.text
    b = w.ada.post("/payments", raw=body, key=k)
    assert b.status_code == 200 and b.json() == a.json()
    err(w.ada.post("/payments", raw=body.replace("999999999999", "999999999998"), key=k),
        409, "idempotency_key_reuse")
    deep = '{"to_handle":"bob","amount":1,"x":' + "[" * 3000 + "]" * 3000 + "}"
    assert w.ada.post("/payments", raw=deep, key=pf.new_key()).status_code in (201, 400)
    assert w.ada.balance() in (9900, 9899)


@L("R-46", "D-11", "R-48")
def test_31_digit_ints_differ():
    w = pf.world()
    k = pf.new_key()
    one = "1000000000000000000000000000001"
    zero = "1000000000000000000000000000000"
    ok(w.ada.post("/payments", raw='{"to_handle":"bob","amount":1,"x":%s}' % one, key=k), 201)
    err(w.ada.post("/payments", raw='{"to_handle":"bob","amount":1,"x":%s}' % zero, key=k),
        409, "idempotency_key_reuse")
    k2 = pf.new_key()
    ok(w.ada.post("/payments", raw='{"to_handle":"bob","amount":1,"x":%s}' % zero, key=k2), 201)
    assert w.ada.post("/payments", raw='{"to_handle":"bob","amount":1,"x":1e30}',
                      key=k2).status_code == 200
    err(w.ada.post("/payments", raw='{"to_handle":"bob","amount":1,"x":true}', key=k2),
        409, "idempotency_key_reuse")
    assert w.ada.balance() == 9998
