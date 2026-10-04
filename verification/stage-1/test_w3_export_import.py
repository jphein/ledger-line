"""W3: export / import (R-84..R-91, R-40, I-07, S-06, S-08, S-17)."""
import copy

import pytest

import pf
from pf import Api, err, ok

L = pytest.mark.ledger


def export():
    return ok(Api().get("/_test/export"))


def do_import(obj):
    r = Api().post("/_test/import", obj)
    assert r.status_code == 204, f"import: {r.status_code} {r.text[:300]}"
    assert r.content == b""


def observable(w):
    """Everything a caller can see, per seeded user."""
    out = {}
    for h, a in w.users.items():
        out[h] = {"me": a.me(), "activity": sorted(a.activity(), key=lambda p: p["payment_id"]),
                  "requests": sorted(a.requests(), key=lambda q: q["request_id"])}
    return out


def busy_world():
    w = pf.world(pf.fixture(users=[pf.ADA, pf.BOB, pf.CY, pf.DEE, pf.OP],
                            operators=["u_op"]))
    ok(w.ada.pay("bob", 111, note="ünïcødé 😀", visibility="private"), 201)
    q = ok(w.bob.ask("cy", 50), 201)
    ok(w.cy.pay_request(q["request_id"], {"visibility": "public"}), 201)
    ok(w.ada.ask("dee", 99999), 201)
    ok(w.ada.post("/splits", {"amount": 10, "participant_handles": ["bob", "cy", "dee"]},
                  key=pf.new_key()), 201)
    ok(w.op.post("/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "dee", "amount": 5},
        {"from_handle": "dee", "to_handle": "cy", "amount": 5, "visibility": "private"}]},
        key=pf.new_key()), 201)
    return w


@L("R-84")
def test_export_shape():
    pf.world()
    e = export()
    assert e["track"] == "pocketful" and e["format_version"] == 1
    assert isinstance(e["state"], dict)


@L("R-85", "R-89", "I-07")
def test_round_trip_preserves_observable_state_and_tokens():
    w = busy_world()
    before = observable(w)
    e = export()
    do_import(e)
    assert observable(w) == before            # same tokens still work
    e2 = export()
    do_import(e2)
    assert observable(w) == before
    assert pf.total_balance(w) == w.total


@L("R-85", "R-91", "R-89")
def test_import_into_different_state_replaces_it():
    w = busy_world()
    before = observable(w)
    e = export()
    zed = pf.user("u_zed", "zed", 777)
    pf.reset(pf.fixture(users=[zed], payments=[], requests=[]))
    z = pf.login("zed@example.com")
    err(Api(w.ada.token).get("/me"), 401)
    do_import(e)
    assert observable(w) == before
    err(z.get("/me"), 401, "unauthenticated")                 # destination creds gone
    err(Api().post("/auth/login", {"email": "zed@example.com", "password": pf.PW}), 401)
    assert pf.login("ada@example.com").balance() == before["ada"]["me"]["balance"]


@L("R-86")
def test_repeat_import_no_duplicates():
    w = busy_world()
    e = export()
    before = observable(w)
    for _ in range(3):
        do_import(e)
    assert observable(w) == before


@L("R-87", "S-17")
@pytest.mark.parametrize("raw", ["", "{", "not json", "{\"track\": \"pocketful\","])
def test_import_invalid_json_400(raw):
    w = busy_world()
    before = observable(w)
    err(Api().post("/_test/import", raw=raw), 400, "malformed_request")
    assert observable(w) == before


@L("R-87", "S-17")
@pytest.mark.parametrize("mutate", ["no_track", "bad_track", "no_version", "version_2",
                                    "version_str", "no_state", "state_str", "state_list",
                                    "state_null", "empty", "array"])
def test_import_invalid_object_422(mutate):
    w = busy_world()
    before = observable(w)
    e = export()
    bad = copy.deepcopy(e)
    if mutate == "no_track":
        del bad["track"]
    elif mutate == "bad_track":
        bad["track"] = "tablekeeper"
    elif mutate == "no_version":
        del bad["format_version"]
    elif mutate == "version_2":
        bad["format_version"] = 2
    elif mutate == "version_str":
        bad["format_version"] = "1"
    elif mutate == "no_state":
        del bad["state"]
    elif mutate == "state_str":
        bad["state"] = "nope"
    elif mutate == "state_list":
        bad["state"] = []
    elif mutate == "state_null":
        bad["state"] = None
    elif mutate == "empty":
        bad = {}
    if mutate == "array":
        r = Api().post("/_test/import", [e])
        assert r.status_code in (400, 422), r.text
    else:
        err(Api().post("/_test/import", bad), 422, "validation_failed")
    assert observable(w) == before


@L("R-87", "S-17")
def test_import_garbled_state_422_changes_nothing():
    w = busy_world()
    before = observable(w)
    e = export()
    bad = copy.deepcopy(e)
    # blank out every top-level member of the opaque state with the wrong type
    bad["state"] = {k: "garbage" for k in e["state"]}
    err(Api().post("/_test/import", bad), 422, "validation_failed")
    assert observable(w) == before


@L("R-88")
def test_export_is_snapshot():
    w = busy_world()
    before = observable(w)
    e = export()
    ok(w.ada.pay("bob", 1), 201)
    ok(w.bob.ask("ada", 1), 201)
    assert export() != e
    do_import(e)
    assert observable(w) == before


@L("R-89", "S-06")
def test_idempotency_records_survive_import():
    w = busy_world()
    kp, kr, kpay, ks, kset = (pf.new_key() for _ in range(5))
    p = ok(w.ada.pay("bob", 7, key=kp), 201)
    q = ok(w.ada.ask("bob", 8, key=kr), 201)
    q2 = ok(w.bob.ask("ada", 9), 201)
    pp = ok(w.ada.pay_request(q2["request_id"], {}, key=kpay), 201)
    sbody = {"amount": 3, "participant_handles": ["cy"]}
    s = ok(w.ada.post("/splits", sbody, key=ks), 201)
    tbody = {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 1}]}
    st = ok(w.op.post("/settlements", tbody, key=kset), 201)
    e = export()
    pf.reset(pf.fixture())
    do_import(e)
    bal = {h: a.balance() for h, a in w.users.items()}
    assert ok(w.ada.pay("bob", 7, key=kp), 200) == p
    assert ok(w.ada.ask("bob", 8, key=kr), 200) == q
    assert ok(w.ada.pay_request(q2["request_id"], {}, key=kpay), 200) == pp
    assert ok(w.ada.post("/splits", sbody, key=ks), 200) == s
    assert ok(w.op.post("/settlements", tbody, key=kset), 200) == st
    err(w.ada.pay("bob", 70, key=kp), 409, "idempotency_key_reuse")
    assert {h: a.balance() for h, a in w.users.items()} == bal


@L("R-89", "S-08")
def test_failed_key_reusable_after_import():
    w = busy_world()
    k = pf.new_key()
    err(w.dee.pay("ada", 10**8, key=k), 409, "insufficient_funds")
    do_import(export())
    ok(w.dee.pay("ada", 1, key=k), 201)


@L("R-89")
def test_import_preserves_password_login_and_operator():
    w = busy_world()
    ok(Api().post("/auth/signup", {"email": "late@x.com", "password": "late-pass-1",
                                   "display_name": "Late"}), 201)
    e = export()
    pf.reset(pf.fixture())
    do_import(e)
    late = ok(Api().post("/auth/login", {"email": "late@x.com", "password": "late-pass-1"}))
    assert Api(late["token"]).me()["handle"] == "late"
    op = pf.login("op@example.com")
    ok(op.post("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob",
                                                "amount": 1}]}, key=pf.new_key()), 201)
    err(w.ada.post("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob",
                                                   "amount": 1}]}, key=pf.new_key()), 403)


@L("R-89")
def test_import_preserves_settlement_membership_and_ids():
    w = busy_world()
    members = [p for p in w.cy.activity() if p["settlement_id"] is not None]
    assert members
    e = export()
    pf.reset(pf.fixture())
    do_import(e)
    assert [p for p in w.cy.activity() if p["settlement_id"] is not None] == members


@L("R-90")
def test_ids_continue_without_collision():
    w = busy_world()
    old_p = {p["payment_id"] for a in w.users.values() for p in a.activity()}
    old_q = {q["request_id"] for a in w.users.values() for q in a.requests()}
    e = export()
    pf.reset(pf.fixture())
    do_import(e)
    new_p = {ok(w.ada.pay("bob", 1), 201)["payment_id"] for _ in range(5)}
    new_q = {ok(w.ada.ask("bob", 1), 201)["request_id"] for _ in range(5)}
    assert not (new_p & old_p) and len(new_p) == 5
    assert not (new_q & old_q) and len(new_q) == 5
    s = ok(Api().post("/auth/signup", {"email": "fresh@x.com", "password": "12345678",
                                       "display_name": "F"}), 201)
    assert s["user_id"] not in {a.user_id for a in w.users.values()}


@L("R-91")
def test_reset_clears_imported_state():
    w = busy_world()
    e = export()
    do_import(e)
    pf.reset(pf.fixture(users=[pf.BOB], payments=[], requests=[]))
    err(Api(w.ada.token).get("/me"), 401, "unauthenticated")
    err(Api(w.bob.token).get("/me"), 401, "unauthenticated")
    assert pf.login("bob@example.com").activity() == []
