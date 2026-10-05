"""X3 browser suite: requests, split and authorizations screens, product/visual quality,
and the browser half of the upgrade (R-232).

Ledger lines R-251..R-267, S-204..S-206, S-214, R-232 (browser). Behaviour through the UI;
money and server state through the JSON API. Screenshots go to $UI_SHOTS
(default /tmp/df-prover-shots) for the human-judged lines R-259..R-263.
"""
import re
import time

import pytest

import pf
import pf2
from ui import *  # noqa: F401,F403
from ui import (ALL_ROUTES, CONTRAST_JS, Hold, L, NAV_JS, PUBLIC_ROUTES, SIGNED_IN_ROUTES,
                UNLABELLED_JS, assert_text, body_of, close_page, commit_then_lose, dec,
                dom_testids, expect, fill_authorize, fill_pay, fmt, focus_problems, font_px,
                goto, key_of, new_page, no_hscroll, plain_fixture, rich_fixture, set_value,
                settle, shot, sign_in_as, style_of, submit_and_response, tid)

WIDTHS = [375, 1280]
# Something that proves the screen's data (not just its shell) has loaded.
DATA_MARK = {"/": "activity-item-p_1", "/requests": "request-item-rq_1",
             "/split": "split-amount", "/authorizations": "authorization-item-a_1",
             "/login": "login-email", "/signup": "signup-email"}


def item(page, kind, i):
    return tid(page, f"{kind}-item-{i}")


# ================================================================ requests screen

@L("R-251")
def test_requests_screen_lists_and_buttons(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/requests")
    inc, out = tid(page, "incoming-list"), tid(page, "outgoing-list")
    # rq_1 bob asks ada (pending), rq_4 cy asks ada (cancelled): incoming
    # rq_3 ada asks bob (pending), rq_2 ada asks cy (declined): outgoing
    expected = {"rq_1": (inc, "pending", 1200), "rq_4": (inc, "cancelled", 250),
                "rq_3": (out, "pending", 700), "rq_2": (out, "declined", 300)}
    for rid, (lst, status, amount) in expected.items():
        expect(tid(lst, f"request-item-{rid}")).to_have_attribute("data-status", status)
        assert_text(tid(page, f"request-amount-{rid}"), fmt(amount, 2, "EUR"))
    for rid in expected:
        incoming_pending = rid == "rq_1"
        outgoing_pending = rid == "rq_3"
        expect(tid(page, f"request-pay-{rid}")).to_have_count(int(incoming_pending))
        expect(tid(page, f"request-decline-{rid}")).to_have_count(int(incoming_pending))
        expect(tid(page, f"request-cancel-{rid}")).to_have_count(int(outgoing_pending))
    expect(tid(page, "empty-requests")).to_have_count(0)
    expect(tid(page, "request-error")).to_have_count(0)
    api_ids = {q["request_id"] for q in w.ada.requests()}
    shown = set(dom_testids(page, "incoming-list", "request-item-")
                + dom_testids(page, "outgoing-list", "request-item-"))
    assert shown == api_ids, (shown, api_ids)


@L("R-251")
def test_requests_screen_other_party_view(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "bob", "/requests")
    # bob is the requester of rq_1 (outgoing pending) and payer of rq_3 (incoming pending)
    expect(tid(tid(page, "outgoing-list"), "request-item-rq_1")).to_be_visible()
    expect(tid(page, "request-cancel-rq_1")).to_have_count(1)
    expect(tid(page, "request-pay-rq_1")).to_have_count(0)
    expect(tid(tid(page, "incoming-list"), "request-item-rq_3")).to_be_visible()
    expect(tid(page, "request-pay-rq_3")).to_have_count(1)
    expect(tid(page, "request-cancel-rq_3")).to_have_count(0)
    expect(tid(page, "request-item-rq_2")).to_have_count(0)   # not bob's


@L("R-251")
def test_empty_requests(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "dee", "/requests")
    expect(tid(page, "empty-requests")).to_be_visible()
    assert tid(page, "empty-requests").inner_text().strip()
    expect(page.locator("[data-testid^='request-item-']")).to_have_count(0)


@L("R-251", "R-246")
def test_pay_request_through_ui(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/requests")
    resp = submit_and_response(page, "request-pay-rq_1", "/requests/rq_1/pay")
    assert resp.status == 201, resp.text()
    assert key_of(page.rec.posts("/requests/rq_1/pay")[0]), "pay sent without a key"
    expect(item(page, "request", "rq_1")).to_have_attribute("data-status", "paid")
    expect(tid(page, "request-pay-rq_1")).to_have_count(0)
    expect(tid(page, "request-decline-rq_1")).to_have_count(0)
    expect(tid(page, "request-error")).to_have_count(0)
    (q,) = [q for q in w.ada.requests() if q["request_id"] == "rq_1"]
    assert q["status"] == "paid" and q["payment_id"]
    assert pf2.me(w.ada)["total"] == 8800 and pf2.me(w.bob)["total"] == 3700


@L("R-251")
def test_decline_request_through_ui(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/requests")
    tid(page, "request-decline-rq_1").click()
    expect(item(page, "request", "rq_1")).to_have_attribute("data-status", "declined")
    expect(tid(page, "request-pay-rq_1")).to_have_count(0)
    assert [q["status"] for q in w.bob.requests() if q["request_id"] == "rq_1"] == ["declined"]
    assert w.ada.balance() == 10000


@L("R-251")
def test_cancel_request_through_ui(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/requests")
    tid(page, "request-cancel-rq_3").click()
    expect(item(page, "request", "rq_3")).to_have_attribute("data-status", "cancelled")
    expect(tid(page, "request-cancel-rq_3")).to_have_count(0)
    assert [q["status"] for q in w.bob.requests() if q["request_id"] == "rq_3"] == ["cancelled"]


@L("R-252", "S-214", "R-251")
def test_stale_pay_button_after_cancel_elsewhere(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/requests")
    expect(tid(page, "request-pay-rq_1")).to_be_visible()
    ok(w.bob.post("/requests/rq_1/cancel", {}))          # the other party cancels
    resp = submit_and_response(page, "request-pay-rq_1", "/requests/rq_1/pay")
    assert resp.status == 409
    expect(tid(page, "request-error")).to_be_visible()
    assert tid(page, "request-error").inner_text().strip()
    expect(tid(page, "request-pay-rq_1")).to_have_count(0)
    expect(item(page, "request", "rq_1")).to_have_attribute("data-status", "cancelled")
    assert w.ada.balance() == 10000 and w.bob.balance() == 2500


@L("S-214", "R-251")
def test_stale_decline_and_cancel_buttons(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/requests")
    expect(tid(page, "request-decline-rq_1")).to_be_visible()
    ok(w.bob.post("/requests/rq_1/cancel", {}))
    ok(w.bob.pay_request("rq_3"), 201)                   # bob pays ada's outgoing rq_3
    tid(page, "request-decline-rq_1").click()
    expect(tid(page, "request-error")).to_be_visible()
    expect(item(page, "request", "rq_1")).to_have_attribute("data-status", "cancelled")
    expect(tid(page, "request-decline-rq_1")).to_have_count(0)
    tid(page, "request-cancel-rq_3").click()
    expect(item(page, "request", "rq_3")).to_have_attribute("data-status", "paid")
    expect(tid(page, "request-cancel-rq_3")).to_have_count(0)
    expect(tid(page, "request-error")).to_be_visible()


@L("R-251")
def test_short_payer_gets_request_error_and_keeps_button(page):
    w = pf.world(rich_fixture())
    ok(w.ada.ask("dee", 100, note="dee is short"), 201)
    (q,) = [q for q in w.dee.requests() if q["note"] == "dee is short"]
    sign_in_as(page, w, "dee", "/requests")
    rid = q["request_id"]
    resp = submit_and_response(page, f"request-pay-{rid}", f"/requests/{rid}/pay")
    assert resp.status == 409
    expect(tid(page, "request-error")).to_be_visible()
    expect(item(page, "request", rid)).to_have_attribute("data-status", "pending")
    expect(tid(page, f"request-pay-{rid}")).to_be_visible()   # still pending: still payable


# ================================================================ split screen

def split_preview(page, amount, handles, shares, mu=2, cur="EUR"):
    set_value(tid(page, "split-amount"), amount)
    set_value(tid(page, "split-handles"), handles)
    expect(tid(page, "split-preview")).to_be_visible()
    for h, s in zip(handles.split(","), shares):
        loc = tid(tid(page, "split-preview"), f"split-share-{h}")
        assert_text(loc, fmt(s, mu, cur))
    assert page.locator("[data-testid^='split-share-']").count() == len(shares)


@L("R-253", "R-254")
@pytest.mark.parametrize("amount,handles,minor,shares", [
    ("10.00", "ada,bob,cy", 1000, [334, 333, 333]),
    ("0.01", "ada,bob,cy", 1, [1, 0, 0]),
    ("10.00", "cy,bob,ada", 1000, [334, 333, 333]),
    ("9.99", "bob,cy,dee", 999, [333, 333, 333]),
    ("0.05", "ada,bob,cy,dee", 5, [2, 1, 1, 1]),
])
def test_split_preview_before_post_then_server_agrees(page, amount, handles, minor, shares):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/split")
    set_value(tid(page, "split-note"), "dinner")
    split_preview(page, amount, handles, shares)
    assert page.rec.posts("/splits") == [], "preview must not post"
    preview = {h: tid(page, f"split-share-{h}").inner_text().strip()
               for h in handles.split(",")}
    resp = submit_and_response(page, "split-submit", "/splits")
    assert resp.status == 201, resp.text()
    body = body_of(page.rec.posts("/splits")[0])
    assert body["amount"] == minor and body["participant_handles"] == handles.split(",")
    srv = resp.json()["shares"]
    assert [s["handle"] for s in srv] == handles.split(",")
    assert {s["handle"]: fmt(s["amount"], 2, "EUR") for s in srv} == preview
    expect(tid(page, "split-error")).to_have_count(0)
    for h, s in zip(handles.split(","), shares):
        if h == "ada":
            continue
        got = [q for q in w.users[h].requests("direction=incoming") if q["note"] == "dinner"]
        assert [q["amount"] for q in got] == [s], (h, got)


@L("R-253", "R-254")
@pytest.mark.parametrize("cur,mu,amount,shares", [("JPY", 0, "10", [4, 3, 3]),
                                                  ("BHD", 3, "1", [334, 333, 333]),
                                                  ("BHD", 3, "0.001", [1, 0, 0])])
def test_split_preview_other_currencies(page, cur, mu, amount, shares):
    w = pf.world(plain_fixture(cur, mu))
    sign_in_as(page, w, "ada", "/split")
    split_preview(page, amount, "ada,bob,cy", shares, mu, cur)
    assert page.rec.posts("/splits") == []


@L("R-253", "R-254")
def test_split_preview_follows_edits(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/split")
    split_preview(page, "10.00", "ada,bob,cy", [334, 333, 333])
    split_preview(page, "10.00", "bob,ada", [500, 500])
    expect(tid(page, "split-share-cy")).to_have_count(0)
    split_preview(page, "0.10", "bob,ada,cy", [4, 3, 3])
    assert page.rec.posts("/splits") == []


@L("R-253")
@pytest.mark.parametrize("amount,handles,sends", [("10.00", "ada,ghost", True),
                                                  ("10.00", "bob,bob", True),
                                                  ("10.005", "ada,bob", False),
                                                  ("abc", "ada,bob", False)])
def test_split_error(page, amount, handles, sends):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/split")
    set_value(tid(page, "split-amount"), amount)
    set_value(tid(page, "split-handles"), handles)
    set_value(tid(page, "split-note"), "bad split")
    tid(page, "split-submit").click()
    expect(tid(page, "split-error")).to_be_visible()
    settle(page, 300)
    assert bool(page.rec.posts("/splits")) == sends
    assert [q for q in w.bob.requests() if q["note"] == "bad split"] == []


# ================================================================ wallet with holds

@L("R-255", "R-258", "R-260", "D-214")
@pytest.mark.parametrize("width", WIDTHS)
def test_available_is_headline_with_seeded_hold(browser, width):
    w = pf.world(pf2.fixture2(authorizations=[pf2.seed_auth("a_1", "u_ada", "u_bob", 2000)]))
    page = new_page(browser, width=width)
    try:
        sign_in_as(page, w, "ada", "/")
        av, bal, held = (tid(page, f"wallet-{k}") for k in ("available", "balance", "held"))
        assert_text(av, "80.00 EUR")
        expect(av).to_have_attribute("data-amount", "8000")
        assert_text(bal, "100.00 EUR")
        expect(bal).to_have_attribute("data-amount", "10000")
        assert_text(held, "20.00 EUR")
        expect(held).to_have_attribute("data-amount", "2000")
        fa, fb, fh = font_px(av), font_px(bal), font_px(held)
        assert fa > fb and fa > fh, f"available {fa}px is not the headline (total {fb}, held {fh})"
        m = pf2.me(w.ada)
        assert (m["total"], m["available"], m["held"]) == (10000, 8000, 2000)
    finally:
        close_page(page)


@L("R-255", "S-207")
@pytest.mark.parametrize("auths", [
    [],
    [pf2.seed_auth("a_9", "u_ada", "u_bob", 2000, status="voided")],
    [pf2.seed_auth("a_9", "u_ada", "u_bob", 2000, expires_at=pf2.in_hours(-2))],
], ids=["none", "voided", "expired-by-clock"])
def test_held_absent_at_zero(page, auths):
    w = pf.world(pf2.fixture2(authorizations=auths))
    sign_in_as(page, w, "ada", "/")
    assert_text(tid(page, "wallet-available"), "100.00 EUR")
    expect(tid(page, "wallet-available")).to_have_attribute("data-amount", "10000")
    assert_text(tid(page, "wallet-balance"), "100.00 EUR")
    expect(tid(page, "wallet-held")).to_have_count(0)


@L("R-256", "R-258", "R-246")
def test_authorize_form_creates_hold(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_authorize(page, "bob", "20.00", "deposit", "private")
    resp = submit_and_response(page, "authorize-submit", "/authorizations")
    assert resp.status == 201, resp.text()
    post = page.rec.posts("/authorizations")[0]
    assert key_of(post)
    assert body_of(post) == {**body_of(post), "to_handle": "bob", "amount": 2000,
                             "note": "deposit", "visibility": "private"}
    assert_text(tid(page, "wallet-available"), "80.00 EUR")
    assert_text(tid(page, "wallet-held"), "20.00 EUR")
    assert_text(tid(page, "wallet-balance"), "100.00 EUR")
    expect(tid(page, "authorize-error")).to_have_count(0)
    m = pf2.me(w.ada)
    assert (m["held"], m["available"]) == (2000, 8000)
    (a,) = pf2.auths(w.ada, "direction=outgoing")
    assert a["status"] == "open" and a["amount"] == 2000 and a["note"] == "deposit"


@L("R-256")
@pytest.mark.parametrize("seed_hold,typed", [(None, "5.01"), (400, "2.00")],
                         ids=["over-total", "over-available"])
def test_authorize_insufficient_available_shows_error(page, seed_hold, typed):
    auths = [pf2.seed_auth("a_1", "u_cy", "u_bob", seed_hold)] if seed_hold else []
    w = pf.world(pf2.fixture2(authorizations=auths))
    sign_in_as(page, w, "cy", "/")
    fill_authorize(page, "bob", typed)
    resp = submit_and_response(page, "authorize-submit", "/authorizations")
    assert resp.status == 409 and resp.json()["error"]["code"] == "insufficient_funds"
    expect(tid(page, "authorize-error")).to_be_visible()
    assert pf2.me(w.cy)["held"] == (seed_hold or 0)


@L("R-256")
def test_authorize_exactly_available_succeeds(page):
    w = pf.world(pf2.fixture2(authorizations=[pf2.seed_auth("a_1", "u_cy", "u_bob", 400)]))
    sign_in_as(page, w, "cy", "/")
    fill_authorize(page, "bob", "1.00")
    assert submit_and_response(page, "authorize-submit", "/authorizations").status == 201
    expect(tid(page, "authorize-error")).to_have_count(0)
    assert_text(tid(page, "wallet-available"), "0.00 EUR")
    assert_text(tid(page, "wallet-held"), "5.00 EUR")


@L("R-256", "R-244")
@pytest.mark.parametrize("typed", ["20.005", "abc", ""])
def test_authorize_bad_amount_sends_nothing(page, typed):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_authorize(page, "bob", typed)
    tid(page, "authorize-submit").click()
    expect(tid(page, "authorize-error")).to_be_visible()
    settle(page, 300)
    assert page.rec.posts("/authorizations") == []


@L("R-256")
def test_held_funds_cannot_pay_through_ui(page):
    w = pf.world(pf2.fixture2(authorizations=[pf2.seed_auth("a_1", "u_cy", "u_bob", 400)]))
    sign_in_as(page, w, "cy", "/")
    fill_pay(page, "bob", "2.00")
    assert submit_and_response(page, "pay-submit", "/payments").status == 409
    expect(tid(page, "pay-error")).to_be_visible()
    assert pf2.me(w.cy)["total"] == 500


# ================================================================ authorizations screen

def auth_world():
    w = pf.world(rich_fixture())
    time.sleep(1.1)
    new1 = ok(pf2.authorize(w.ada, "bob", 500, note="new hold"), 201)
    time.sleep(1.1)
    cap = ok(pf2.authorize(w.cy, "ada", 300, note="to capture"), 201)
    ok(pf2.capture(w.ada, cap["authorization_id"], {"amount": 100}), 201)
    return w, new1["authorization_id"], cap["authorization_id"]


@L("R-257", "R-258", "S-205", "S-206")
def test_authorizations_screen_rows(page):
    w, new1, cap = auth_world()
    sign_in_as(page, w, "ada", "/authorizations")
    api = {a["authorization_id"]: a for a in pf2.auths(w.ada)}
    expect(item(page, "authorization", new1)).to_be_visible()
    order = dom_testids(page, "authorization-list", "authorization-item-")
    assert set(order) == set(api), (order, sorted(api))
    ts = [pf2.parse_ts(api[i]["created_at"]) for i in order]
    assert all(a >= b for a, b in zip(ts, ts[1:])), f"not newest first: {order}"
    assert order.index(cap) < order.index(new1), order
    # (incoming?, status) per row from the API; the screen must agree
    for i, a in api.items():
        incoming = a["to_handle"] == "ada"
        st = a["status"]
        expect(item(page, "authorization", i)).to_have_attribute("data-status", st)
        assert_text(tid(page, f"authorization-amount-{i}"), fmt(a["amount"], 2, "EUR"))
        assert_text(tid(page, f"authorization-expires-{i}"), a["expires_at"])
        assert pf.RFC3339.match(a["expires_at"])
        inc_open = incoming and st == "open"
        expect(tid(page, f"authorization-capture-{i}")).to_have_count(int(inc_open))
        expect(tid(page, f"authorization-capture-amount-{i}")).to_have_count(int(inc_open))
        expect(tid(page, f"authorization-void-{i}")).to_have_count(
            int(not incoming and st == "open"))
        expect(tid(page, f"authorization-captured-{i}")).to_have_count(int(st == "captured"))
        if inc_open:
            expect(tid(page, f"authorization-capture-amount-{i}")).to_have_value(
                dec(a["remaining_amount"], 2))
        if st == "captured":
            assert_text(tid(page, f"authorization-captured-{i}"),
                        fmt(a["captured_amount"], 2, "EUR"))
    # spot checks against the seeds
    assert api["a_6"]["status"] == "expired"
    expect(tid(page, "authorization-capture-amount-a_2")).to_have_value("20.00")
    assert_text(tid(page, f"authorization-captured-{cap}"), "1.00 EUR")
    expect(tid(page, "empty-authorizations")).to_have_count(0)
    expect(tid(page, "authorization-error")).to_have_count(0)


@L("S-206", "R-257")
@pytest.mark.parametrize("cur,mu,amount,text", [("EUR", 2, 2000, "20.00"),
                                                ("JPY", 0, 1200, "1200"),
                                                ("BHD", 3, 1250, "1.250")])
def test_capture_prefill_is_decimal_remaining(page, cur, mu, amount, text):
    fix = pf2.fixture2(authorizations=[pf2.seed_auth("a_2", "u_bob", "u_ada", amount)],
                       users=[pf.ADA, pf.BOB, pf.CY, pf.DEE], payments=[], requests=[],
                       currency=cur, minor_units=mu)
    w = pf.world(fix)
    sign_in_as(page, w, "ada", "/authorizations")
    expect(tid(page, "authorization-capture-amount-a_2")).to_have_value(text)
    assert_text(tid(page, "authorization-amount-a_2"), fmt(amount, mu, cur))


@L("R-257")
def test_empty_authorizations(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "dee", "/authorizations")
    expect(tid(page, "empty-authorizations")).to_be_visible()
    assert tid(page, "empty-authorizations").inner_text().strip()
    expect(page.locator("[data-testid^='authorization-item-']")).to_have_count(0)


@L("R-257", "R-246")
def test_partial_capture_through_ui(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/authorizations")
    set_value(tid(page, "authorization-capture-amount-a_2"), "5.00")
    resp = submit_and_response(page, "authorization-capture-a_2", "/authorizations/a_2/capture")
    assert resp.status == 201, resp.text()
    post = page.rec.posts("/authorizations/a_2/capture")[0]
    assert key_of(post) and body_of(post)["amount"] == 500
    a = pf2.auth_of(w.ada, "a_2")
    assert a["captured_amount"] == 500
    assert pf2.me(w.ada)["total"] == 10500 and pf2.me(w.bob)["total"] == 2000
    expect(item(page, "authorization", "a_2")).to_have_attribute("data-status", a["status"])
    if a["status"] == "captured":
        assert_text(tid(page, "authorization-captured-a_2"), "5.00 EUR")
        expect(tid(page, "authorization-capture-a_2")).to_have_count(0)
    else:   # the UI chose final:false; remainder stays held and is pre-filled
        expect(tid(page, "authorization-capture-amount-a_2")).to_have_value(
            dec(a["remaining_amount"], 2))
    expect(tid(page, "authorization-error")).to_have_count(0)


@L("R-257")
def test_full_capture_with_prefill(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/authorizations")
    resp = submit_and_response(page, "authorization-capture-a_2", "/authorizations/a_2/capture")
    assert resp.status == 201
    expect(item(page, "authorization", "a_2")).to_have_attribute("data-status", "captured")
    assert_text(tid(page, "authorization-captured-a_2"), "20.00 EUR")
    a = pf2.auth_of(w.ada, "a_2")
    assert a["status"] == "captured" and a["captured_amount"] == 2000
    assert pf2.me(w.bob)["total"] == 500


@L("R-257", "R-244")
@pytest.mark.parametrize("typed,sends", [("5.005", False), ("abc", False), ("25.00", True)])
def test_capture_refused_shows_authorization_error(page, typed, sends):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/authorizations")
    set_value(tid(page, "authorization-capture-amount-a_2"), typed)
    tid(page, "authorization-capture-a_2").click()
    expect(tid(page, "authorization-error")).to_be_visible()
    settle(page, 300)
    assert bool(page.rec.posts("/authorizations/a_2/capture")) == sends
    a = pf2.auth_of(w.ada, "a_2")
    assert a["status"] == "open" and a["captured_amount"] == 0


@L("R-257")
def test_void_through_ui(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/authorizations")
    tid(page, "authorization-void-a_1").click()
    expect(item(page, "authorization", "a_1")).to_have_attribute("data-status", "voided")
    expect(tid(page, "authorization-void-a_1")).to_have_count(0)
    assert pf2.auth_of(w.ada, "a_1")["status"] == "voided"
    m = pf2.me(w.ada)
    assert m["held"] == 0 and m["available"] == 10000


@L("S-214", "R-257")
def test_stale_capture_button(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/authorizations")
    expect(tid(page, "authorization-capture-a_2")).to_be_visible()
    ok(pf2.void(w.bob, "a_2"))                              # payer voids elsewhere
    tid(page, "authorization-capture-a_2").click()
    expect(tid(page, "authorization-error")).to_be_visible()
    expect(item(page, "authorization", "a_2")).to_have_attribute("data-status", "voided")
    expect(tid(page, "authorization-capture-a_2")).to_have_count(0)
    assert pf2.me(w.ada)["total"] == 10000


@L("S-214", "R-257")
def test_stale_void_button(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/authorizations")
    expect(tid(page, "authorization-void-a_1")).to_be_visible()
    ok(pf2.capture(w.bob, "a_1"), 201)                      # receiver captures elsewhere
    tid(page, "authorization-void-a_1").click()
    expect(tid(page, "authorization-error")).to_be_visible()
    expect(item(page, "authorization", "a_1")).to_have_attribute("data-status", "captured")
    expect(tid(page, "authorization-void-a_1")).to_have_count(0)
    assert pf2.me(w.ada)["total"] == 8000


# ================================================================ upgrade in the browser

@L("R-232", "S-204")
def test_upgrade_between_requests_keeps_session_and_retry(page):
    w = pf.world(pf.fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", "15.00", "pre-upgrade", "public")
    lose = commit_then_lose(page)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-uncertain")).to_be_visible()
    lose.remove()
    export = ok(pf.Api().get("/_test/export"))
    pf.reset(plain_fixture(balances=(1, 2, 3, 4)))          # a different service state
    ok(pf.Api().post("/_test/import", export), 204)
    # no reload: the same page retries the same body and key
    r2 = submit_and_response(page, "pay-submit", "/payments")
    assert r2.status == 200, f"retry after import must replay, got {r2.status}"
    p1, p2 = page.rec.posts("/payments")
    assert key_of(p1) == key_of(p2) and body_of(p1) == body_of(p2)
    expect(tid(page, "pay-uncertain")).to_have_count(0)
    expect(tid(page, "pay-error")).to_have_count(0)
    assert_text(tid(page, "wallet-balance"), "85.00 EUR")
    assert_text(tid(page, "current-handle"), "ada")
    assert w.ada.balance() == 8500 and w.bob.balance() == 4000
    assert len([p for p in w.ada.activity() if p["note"] == "pre-upgrade"]) == 1
    # the pre-upgrade pending request is payable from the requests screen
    goto(page, "/requests")
    assert_text(tid(page, "current-handle"), "ada")
    resp = submit_and_response(page, "request-pay-rq_1", "/requests/rq_1/pay")
    assert resp.status == 201
    expect(item(page, "request", "rq_1")).to_have_attribute("data-status", "paid")
    assert w.ada.balance() == 8500 - 1200


# ================================================================ product and visual checks

def each_route(page, w, check, routes=ALL_ROUTES) -> dict:
    """Visit routes (public ones signed out first), run check(route) -> problems."""
    problems = {}
    for r in [r for r in routes if r in PUBLIC_ROUTES]:
        goto(page, r, DATA_MARK[r])
        got = check(r)
        if got:
            problems[r] = got
    signed = [r for r in routes if r in SIGNED_IN_ROUTES]
    if signed:
        sign_in_as(page, w, "ada", "/")
        for r in signed:
            goto(page, r, DATA_MARK[r])
            got = check(r)
            if got:
                problems[r] = got
    return problems


@pytest.fixture(params=WIDTHS, ids=lambda x: f"w{x}")
def wpage(browser, request):
    pg = new_page(browser, width=request.param)
    pg.width = request.param
    try:
        yield pg
    finally:
        close_page(pg)


@L("R-265", "D-214")
def test_no_horizontal_scroll(wpage):
    w = pf.world(rich_fixture())

    def check(route):
        good, sw, iw = no_hscroll(wpage)
        return None if good else f"scrollWidth {sw} > innerWidth {iw}"
    assert each_route(wpage, w, check) == {}


@L("R-266", "D-214")
def test_inputs_have_visible_labels(wpage):
    w = pf.world(rich_fixture())
    assert each_route(wpage, w, lambda r: wpage.evaluate(UNLABELLED_JS)) == {}


@L("R-266", "D-214")
def test_keyboard_focus_visible(wpage):
    w = pf.world(rich_fixture())
    assert each_route(wpage, w, lambda r: focus_problems(wpage)) == {}


@L("R-266", "D-214")
def test_text_contrast(wpage):
    w = pf.world(rich_fixture())

    def check(route):
        res = wpage.evaluate(CONTRAST_JS)
        if res["checked"] == 0:
            return [f"no text measurable ({res['unknown']} on background images)"]
        return res["fails"][:10]
    assert each_route(wpage, w, check) == {}


@L("R-267")
def test_navigation_consistent(wpage):
    w = pf.world(rich_fixture())
    navs = {}

    def check(route):
        navs[route] = sorted(map(tuple, wpage.evaluate(NAV_JS)))
    each_route(wpage, w, check, SIGNED_IN_ROUTES)
    first = navs["/"]
    assert first, "no links inside nav/[role=navigation]/header on /"
    paths = {p for p, _ in first}
    assert {"/", "/requests", "/split", "/authorizations"} <= paths, first
    for r, n in navs.items():
        assert n == first, f"navigation on {r} differs from /: {n} vs {first}"


@L("R-264", "S-205")
def test_human_friendly_formatting(page):
    w = pf.world(rich_fixture())
    ok(w.ada.pay("bob", 123, note="ui fmt"), 201)
    pids = [p["payment_id"] for p in w.ada.activity()]
    rids = [q["request_id"] for q in w.ada.requests()]
    uids = [u["id"] for u in w.fixture["users"]]

    def raw_ids(text, ids):
        return [i for i in ids if re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])", text)]
    sign_in_as(page, w, "ada", "/")
    expect(tid(page, "activity-item-p_1")).to_be_visible()
    feed = tid(page, "activity-list").inner_text()
    assert not pf.RFC3339.search(feed) and not re.search(r"\d{4}-\d{2}-\d{2}T\d", feed), feed
    assert raw_ids(feed, pids + uids) == [], f"technical ids visible in the feed: {feed!r}"
    goto(page, "/requests", "request-item-rq_1")
    text = tid(page, "incoming-list").inner_text() + tid(page, "outgoing-list").inner_text()
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d", text), text
    assert raw_ids(text, rids + uids) == [], f"technical ids on /requests: {text!r}"
    goto(page, "/authorizations", "authorization-item-a_1")
    text = tid(page, "authorization-list").inner_text()
    for a in pf2.auths(w.ada):
        exp = tid(page, f"authorization-expires-{a['authorization_id']}").inner_text().strip()
        assert exp == a["expires_at"] and pf.RFC3339.match(exp)
        text = text.replace(exp, "")
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d", text), \
        f"raw timestamps outside authorization-expires: {text!r}"
    assert raw_ids(text, uids) == []


@L("R-261")
def test_privacy_and_status_readable(page):
    """Automated part of R-261: privacy and request status are said in words (or an
    accessible name), not only as data attributes."""
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "bob", "/")      # bob sees p_1 (public) and p_2 (private)
    priv = tid(page, "activity-item-p_2")
    expect(priv).to_be_visible()
    said = priv.evaluate("""e => (e.innerText + ' ' + [...e.querySelectorAll('*')].concat([e])
        .map(x => (x.getAttribute('aria-label') || '') + ' ' + (x.getAttribute('title') || ''))
        .join(' ')).toLowerCase()""")
    assert "private" in said, f"private payment not marked private for people: {said!r}"
    words = {"pending": ("pending", "waiting", "awaiting", "open"),
             "declined": ("declined", "rejected"),
             "cancelled": ("cancelled", "canceled", "withdrawn")}
    goto(page, "/requests", "request-item-rq_1")
    for rid, st in (("rq_1", "pending"), ("rq_3", "pending")):
        txt = item(page, "request", rid).inner_text().lower()
        assert any(x in txt for x in words[st]), f"{rid} status {st} not readable: {txt!r}"
    sign_in_as(page, w, "ada", "/requests")
    for rid, st in (("rq_2", "declined"), ("rq_4", "cancelled")):
        txt = item(page, "request", rid).inner_text().lower()
        assert any(x in txt for x in words[st]), f"{rid} status {st} not readable: {txt!r}"


@L("R-262")
def test_consistent_type_and_primary_actions(page):
    """Automated part of R-262: one body font across routes; submit buttons stand out
    from their surroundings (filled, or a border with 3:1 contrast)."""
    w = pf.world(rich_fixture())
    fonts = {}
    standout_js = """e => {
      const cv = document.createElement('canvas'); cv.width = cv.height = 1;
      const cx = cv.getContext('2d', {willReadFrequently: true});
      const rgba = c => { cx.clearRect(0,0,1,1); cx.fillStyle = '#000'; cx.fillStyle = c;
        cx.fillRect(0,0,1,1); const d = cx.getImageData(0,0,1,1).data;
        return [d[0], d[1], d[2], d[3] / 255]; };
      const over = (t, b) => [0,1,2].map(i => t[i] * t[3] + b[i] * (1 - t[3]));
      const bgOf = el => { const ls = [];
        for (let x = el; x; x = x.parentElement) { const c = rgba(getComputedStyle(x).backgroundColor);
          if (c[3] > 0) { ls.push(c); if (c[3] >= 1) break; } }
        let b = [255,255,255]; for (let i = ls.length - 1; i >= 0; i--) b = over(ls[i], b); return b; };
      const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92
        : Math.pow((v + 0.055) / 1.055, 2.4); }; return .2126*f(c[0]) + .7152*f(c[1]) + .0722*f(c[2]); };
      const ratio = (a, b) => { const x = lum(a), y = lum(b);
        return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
      const s = getComputedStyle(e); const around = bgOf(e.parentElement);
      const fill = ratio(bgOf(e), around);
      const border = parseFloat(s.borderTopWidth) > 0 ? ratio(over(rgba(s.borderTopColor), around), around) : 1;
      return {fill, border}; }"""
    buttons = {"/login": ["login-submit"], "/signup": ["signup-submit"],
               "/": ["pay-submit"], "/split": ["split-submit"]}
    bad = {}

    def check(route):
        fonts[route] = page.evaluate("() => getComputedStyle(document.body).fontFamily")
        for b in buttons.get(route, []):
            r = tid(page, b).evaluate(standout_js)
            if r["fill"] < 1.5 and r["border"] < 3:
                bad[b] = r
    each_route(page, w, check)
    assert len(set(fonts.values())) == 1, f"body font differs by route: {fonts}"
    assert bad == {}, f"primary actions do not stand out: {bad}"


@L("R-263")
def test_error_and_uncertain_states_distinct(page):
    """Automated part of R-263: refused and uncertain look different; held is styled
    differently from available."""
    w = pf.world(pf2.fixture2(authorizations=[pf2.seed_auth("a_1", "u_ada", "u_bob", 2000)]))
    sign_in_as(page, w, "ada", "/")
    props = ("color", "background-color", "border-top-color", "border-left-color")
    fill_pay(page, "ghost", "1.00")
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-error")).to_be_visible()
    e_style = style_of(tid(page, "pay-error"), *props)
    fill_pay(page, "bob", "1.00", "uncertain")
    lose = commit_then_lose(page)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-uncertain")).to_be_visible()
    lose.remove()
    u_style = style_of(tid(page, "pay-uncertain"), *props)
    assert e_style != u_style, f"pay-error and pay-uncertain look the same: {e_style}"
    a = style_of(tid(page, "wallet-available"), "color", "font-size", "font-weight")
    h = style_of(tid(page, "wallet-held"), "color", "font-size", "font-weight")
    assert a != h, f"available and held look the same: {a}"


@L("R-267")
def test_empty_and_error_states_have_text(page):
    """Automated part of R-267: empty states say something."""
    fix = rich_fixture()
    fix["payments"] = [pf.SEED_PAYMENTS[1]]
    w = pf.world(fix)
    sign_in_as(page, w, "dee", "/")
    for route, t in (("/", "empty-activity"), ("/requests", "empty-requests"),
                     ("/authorizations", "empty-authorizations")):
        goto(page, route)
        expect(tid(page, t)).to_be_visible()
        assert len(tid(page, t).inner_text().strip()) >= 3, f"{t} has no considered text"


@L("R-259", "R-260", "R-261", "R-262", "R-263", "R-265", "R-267")
def test_screenshots_every_route(wpage):
    """Captures every route at this width into $UI_SHOTS. The judgement parts of
    R-259..R-263 (presentation-ready, calm and trustworthy, scannable, consistent visual
    system, distinct states) need human or auditor review of these images; this test only
    captures them and passes."""
    w = pf.world(rich_fixture())
    ok(w.ada.pay("bob", 1234, note="groceries"), 201)

    def check(route):
        name = "home" if route == "/" else route.strip("/")
        shot(wpage, f"route-{name}-{wpage.width}")
    each_route(wpage, w, check)


@L("R-259", "R-263", "R-267")
def test_screenshots_states(browser):
    """Captures loading, success, refused, uncertain, held and empty states at 375 and
    1280 px into $UI_SHOTS for human or auditor review (R-263 distinct states, R-267
    considered empty/loading/error states). Capture only; passes."""
    for width in WIDTHS:
        w = pf.world(pf2.fixture2(authorizations=[
            pf2.seed_auth("a_1", "u_ada", "u_bob", 2000),
            pf2.seed_auth("a_2", "u_bob", "u_ada", 1000)]))
        page = new_page(browser, width=width)
        try:
            sign_in_as(page, w, "ada", "/")
            hold = Hold(page, {"/me", "/activity", "/requests", "/authorizations"},
                        snapshot=False)
            hold.arm()
            page.goto("/")
            page.wait_for_timeout(600)
            shot(page, f"state-loading-home-{width}")
            hold.remove()
            expect(tid(page, "wallet-balance")).to_be_visible()
            shot(page, f"state-held-home-{width}")
            fill_pay(page, "bob", "1.00", "ok")
            submit_and_response(page, "pay-submit", "/payments")
            page.wait_for_timeout(300)
            shot(page, f"state-success-pay-{width}")
            fill_pay(page, "ghost", "1.00")
            tid(page, "pay-submit").click()
            expect(tid(page, "pay-error")).to_be_visible()
            shot(page, f"state-refused-pay-{width}")
            fill_pay(page, "bob", "2.00", "lost")
            lose = commit_then_lose(page)
            tid(page, "pay-submit").click()
            expect(tid(page, "pay-uncertain")).to_be_visible()
            lose.remove()
            shot(page, f"state-uncertain-pay-{width}")
            goto(page, "/authorizations")
            set_value(tid(page, "authorization-capture-amount-a_2"), "99.00")
            tid(page, "authorization-capture-a_2").click()
            expect(tid(page, "authorization-error")).to_be_visible()
            shot(page, f"state-refused-capture-{width}")
        finally:
            close_page(page)
        page = new_page(browser, width=width)
        try:
            sign_in_as(page, w, "dee", "/")
            shot(page, f"state-empty-home-{width}")
            for r in ("/requests", "/authorizations"):
                goto(page, r)
                shot(page, f"state-empty-{r.strip('/')}-{width}")
        finally:
            close_page(page)
