"""W2: /me and POST /payments (R-52..R-62, S-03, S-13)."""
import pytest

import pf
from pf import err, ok

L = pytest.mark.ledger


@L("R-52")
def test_me_exact_keys():
    w = pf.world()
    me = w.bob.me()
    assert set(me) == {"user_id", "display_name", "handle", "balance", "currency",
                       "minor_units"}
    assert type(me["balance"]) is int


@L("R-53", "R-54", "R-99")
def test_payment_201_shape_defaults_and_effect():
    w = pf.world()
    p = ok(w.ada.pay("bob", 1500), 201)
    pf.check_payment(p, from_user_id="u_ada", from_handle="ada", to_user_id="u_bob",
                     to_handle="bob", amount=1500, currency="EUR", note="",
                     visibility="public", request_id=None, settlement_id=None)
    assert w.ada.balance() == 8500 and w.bob.balance() == 4000


@L("R-53")
def test_payment_explicit_fields():
    w = pf.world()
    p = ok(w.bob.pay("cy", 25, note="dinner", visibility="private"), 201)
    pf.check_payment(p, note="dinner", visibility="private", from_handle="bob",
                     to_handle="cy")
    ids = [x["payment_id"] for x in (ok(w.ada.pay("bob", 1), 201),
                                     ok(w.ada.pay("bob", 1), 201))]
    assert len(set(ids + [p["payment_id"], "p_1", "p_2"])) == 5, "ids must be unique"


@L("R-55", "R-61")
def test_insufficient_funds_boundary():
    w = pf.world()
    err(w.cy.pay("bob", 501), 409, "insufficient_funds")
    assert w.cy.balance() == 500 and w.bob.balance() == 2500
    ok(w.cy.pay("bob", 500), 201)
    assert w.cy.balance() == 0
    err(w.cy.pay("bob", 1), 409, "insufficient_funds")
    err(w.dee.pay("ada", 1), 409, "insufficient_funds")
    assert w.bob.balance() == 3000


@L("R-56")
@pytest.mark.parametrize("amount", [0, -1, -1000, 1_000_000_001, 10**18, 1.5, 0.5])
def test_amount_out_of_range_422(amount):
    w = pf.world()
    err(w.ada.pay("bob", amount), 422, "validation_failed")
    assert w.ada.balance() == 10000


@L("R-56")
def test_amount_one_ok():
    w = pf.world()
    ok(w.ada.pay("bob", 1), 201)
    assert w.ada.balance() == 9999


@L("R-57")
def test_self_payment_422():
    w = pf.world()
    err(w.ada.pay("ada", 10), 422, "self_payment")
    err(w.dee.pay("dee", 10), 422, "self_payment")  # even with no funds
    assert w.ada.balance() == 10000


@L("R-58", "S-13")
def test_note_length_code_points():
    w = pf.world()
    ok(w.ada.pay("bob", 1, note="a" * 200), 201)
    ok(w.ada.pay("bob", 1, note="😀" * 200), 201)
    ok(w.ada.pay("bob", 1, note="é" * 200), 201)
    err(w.ada.pay("bob", 1, note="a" * 201), 422, "validation_failed")
    err(w.ada.pay("bob", 1, note="😀" * 201), 422, "validation_failed")
    ok(w.ada.pay("bob", 1, note=""), 201)
    assert w.ada.balance() == 10000 - 4


@L("R-59")
def test_visibility_values():
    w = pf.world()
    ok(w.ada.pay("bob", 1, visibility="public"), 201)
    ok(w.ada.pay("bob", 1, visibility="private"), 201)
    err(w.ada.pay("bob", 1, visibility="Private"), 422, "validation_failed")
    err(w.ada.pay("bob", 1, visibility="hidden"), 422, "validation_failed")


@L("R-60")
@pytest.mark.parametrize("handle", ["nobody", "bob_", "u_bob", "bobb", "x" * 20])
def test_unknown_handle_404(handle):
    w = pf.world()
    err(w.ada.pay(handle, 10), 404, "not_found")
    assert w.ada.balance() == 10000


@L("R-60")
@pytest.mark.parametrize("handle", ["BOB", " bob", "bob ", "", "x" * 21])
def test_ill_formed_handle_never_pays(handle):
    """Spec leaves 404 vs 422 open for ill-formed handles; either, never a payment."""
    w = pf.world()
    r = w.ada.pay(handle, 10)
    assert r.status_code in (404, 422), r.text
    assert w.ada.balance() == 10000 and w.bob.balance() == 2500


@L("R-61", "I-05")
def test_failed_payment_leaves_no_trace():
    w = pf.world()
    before = {h: (a.balance(), len(a.activity())) for h, a in w.users.items()}
    err(w.cy.pay("bob", 10**6), 409, "insufficient_funds")
    err(w.cy.pay("bob", 0), 422)
    err(w.cy.pay("ghost", 1), 404)
    err(w.cy.pay("cy", 1), 422)
    after = {h: (a.balance(), len(a.activity())) for h, a in w.users.items()}
    assert before == after


@L("R-61", "I-05")
def test_payment_visible_in_both_wallets():
    w = pf.world()
    p = ok(w.bob.pay("cy", 77, visibility="private"), 201)
    for a in (w.bob, w.cy):
        got = [x for x in a.activity() if x["payment_id"] == p["payment_id"]]
        assert got == [p], (a.handle, got)
    assert w.bob.balance() == 2500 - 77 and w.cy.balance() == 577


@L("R-62", "S-13")
@pytest.mark.parametrize("note", [
    "  leading and trailing  ",
    "<b>bold</b> &amp; \"quotes\" 'single' \\back\\slash",
    "line1\nline2\r\n\ttab",
    "é vs é",                # NFD vs NFC must not be normalised
    "😀👍🏽👨‍👩‍👧 🇩🇪",
    "​zero‍width﻿",
    "日本語のメモ",
    "\u0000nul",
])
def test_note_verbatim_round_trip(note):
    w = pf.world()
    p = ok(w.ada.pay("bob", 1, note=note), 201)
    assert p["note"] == note
    assert p["note"].encode("utf-8") == note.encode("utf-8")
    got = [x for x in w.bob.activity() if x["payment_id"] == p["payment_id"]]
    assert got and got[0]["note"] == note
    q = ok(w.ada.ask("bob", 1, note=note), 201)
    assert q["note"] == note
    got = [x for x in w.bob.requests() if x["request_id"] == q["request_id"]]
    assert got and got[0]["note"] == note
