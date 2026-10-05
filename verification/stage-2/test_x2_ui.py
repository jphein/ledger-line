"""X2 browser suite: routes, auth screens, wallet home, feed, refresh, uncertainty.

Ledger lines R-235..R-250, S-200..S-203, S-207, S-208, S-212, S-213, I-205 (+ D-209, D-213).
Behaviour is asserted through the UI; money and server state through the JSON API.
"""
import time

import pytest

import pf
import pf2
from ui import *  # noqa: F401,F403
from ui import (BROWSER_ACCEPT, L, LoseResponses, Hold, SIGNED_IN_ROUTES, assert_text,
                body_of, commit_then_lose, dom_testids, fill_pay, fill_request, fmt, goto,
                is_html, key_of, lose_before_server, looks_like_json_page, pay_values,
                plain_fixture, raw_get, rich_fixture, set_value, settle, sign_in,
                sign_in_as, submit_and_response, tid, wait_until, expect,
                new_page, close_page)


def ids_of(api, note):
    return [p["payment_id"] for p in api.activity() if p["note"] == note]


# ================================================================ routes and negotiation

@L("R-235", "S-201")
@pytest.mark.parametrize("route", ["/", "/requests", "/split", "/signup", "/login",
                                   "/authorizations"])
def test_route_serves_html_to_browser_accept(route):
    pf.reset(plain_fixture())
    r = raw_get(route, accept=BROWSER_ACCEPT)
    assert r.status_code == 200, f"{route}: {r.status_code} {r.text[:200]}"
    assert is_html(r), f"{route} with a browser Accept is not HTML: {r.headers}"
    r = raw_get(route, accept="text/html")
    assert r.status_code == 200 and is_html(r), f"{route} with Accept text/html"


@L("R-235", "R-237")
@pytest.mark.parametrize("route", SIGNED_IN_ROUTES)
def test_signed_in_route_reachable_by_url(page, route):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", route)   # waits for the screen's own testid


@L("R-235", "R-237")
@pytest.mark.parametrize("route,marks", [
    ("/login", ["login-email", "login-password", "login-submit"]),
    ("/signup", ["signup-email", "signup-password", "signup-display-name", "signup-submit"]),
])
def test_public_route_reachable_by_url(page, route, marks):
    pf.reset(plain_fixture())
    page.goto(route)
    for m in marks:
        expect(tid(page, m)).to_be_visible()


@L("R-235")
def test_other_screens_reachable_through_ui(page):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/")
    for route in ("/requests", "/split", "/authorizations", "/"):
        link = page.locator(f"a[href='{route}'], a[href='{pf.BASE}{route}']").first
        expect(link).to_be_attached()
        if not link.is_visible():   # collapsed menu: open it by its toggle if there is one
            toggle = page.locator("button[aria-expanded], [aria-controls]").first
            if toggle.count():
                toggle.click()
        link.click()
        expect(tid(page, {"/": "wallet-balance", "/requests": "incoming-list",
                          "/split": "split-amount",
                          "/authorizations": "authorization-list"}[route])).to_be_visible()


@L("R-236", "S-201")
@pytest.mark.parametrize("path,field", [("/requests", "requests"),
                                        ("/authorizations", "authorizations")])
def test_shared_paths_negotiate(path, field):
    w = pf.world(rich_fixture())
    tok = w.ada.token
    # browser-like and plain text/html -> HTML, with or without a token
    for accept in (BROWSER_ACCEPT, "text/html", "application/xhtml+xml,text/html;q=0.9"):
        for t in (tok, None):
            r = raw_get(path, accept=accept, token=t)
            assert r.status_code == 200 and is_html(r), (accept, bool(t), r.status_code,
                                                         r.headers.get("content-type"))
    # no Accept, application/json, */* -> JSON via the ordinary API client
    for headers in (None, {"Accept": "application/json"}, {"Accept": "*/*"}):
        body = ok(w.ada.get(path, headers=headers))
        assert isinstance(body.get(field), list) and "has_more" in body, body
    # the JSON side still requires a token
    err(pf.Api().get(path), 401, "unauthenticated")


@L("R-236", "S-200")
@pytest.mark.parametrize("route,path", [("/requests", "/requests"),
                                        ("/authorizations", "/authorizations")])
def test_ui_fetches_ask_for_json(page, route, path):
    w = pf.world(rich_fixture())
    sign_in_as(page, w, "ada", "/")
    page.rec.clear()
    goto(page, route)
    expect(tid(page, "request-item-rq_1" if path == "/requests"
               else "authorization-item-a_1")).to_be_visible()
    calls = [e for e in page.rec.api_calls() if e["path"] == path and e["method"] == "GET"]
    assert calls, f"the UI did not fetch {path} (server-rendered?): cannot check S-200"
    for e in calls:
        assert "text/html" not in e["headers"].get("accept", ""), e["headers"]


# ================================================================ signup / login

@L("R-238", "S-207", "S-208")
def test_signup_signs_in(page):
    pf.reset(plain_fixture())
    page.goto("/signup")
    expect(tid(page, "auth-error")).to_have_count(0)
    set_value(tid(page, "signup-email"), "Neo.Here@example.com")
    set_value(tid(page, "signup-password"), "long enough pw")
    set_value(tid(page, "signup-display-name"), "Neo Here")
    tid(page, "signup-submit").click()
    assert_text(tid(page, "current-handle"), "neo_here", timeout=10000)
    expect(tid(page, "current-user")).to_contain_text("Neo Here")
    expect(tid(page, "auth-error")).to_have_count(0)
    neo = pf.login("Neo.Here@example.com", "long enough pw")
    assert neo.me()["handle"] == "neo_here" and neo.balance() == 0


@L("R-238", "S-207")
@pytest.mark.parametrize("email,password", [("ada@example.com", "long enough pw"),
                                            ("x@example.com", "short"),
                                            ("not-an-email", "long enough pw")])
def test_signup_refused_shows_auth_error(page, email, password):
    pf.reset(plain_fixture())
    page.goto("/signup")
    set_value(tid(page, "signup-email"), email)
    set_value(tid(page, "signup-password"), password)
    set_value(tid(page, "signup-display-name"), "Someone")
    tid(page, "signup-submit").click()
    expect(tid(page, "auth-error")).to_be_visible()
    assert tid(page, "auth-error").inner_text().strip(), "auth-error is empty"
    expect(tid(page, "current-handle")).to_have_count(0)


@L("R-238", "S-207")
def test_login_screen_no_error_until_wrong_password(page):
    pf.reset(plain_fixture())
    page.goto("/login")
    expect(tid(page, "login-email")).to_be_visible()
    expect(tid(page, "auth-error")).to_have_count(0)
    set_value(tid(page, "login-email"), "ada@example.com")
    set_value(tid(page, "login-password"), "wrong horse")
    tid(page, "login-submit").click()
    expect(tid(page, "auth-error")).to_be_visible()
    expect(tid(page, "current-user")).to_have_count(0)
    # then the right password: signed in, error gone
    set_value(tid(page, "login-password"), pf.PW)
    tid(page, "login-submit").click()
    assert_text(tid(page, "current-handle"), "ada", timeout=10000)
    expect(tid(page, "auth-error")).to_have_count(0)


@L("R-238", "S-208")
def test_current_user_and_handle_on_every_screen(page):
    fix = rich_fixture()
    fix["users"][0]["display_name"] = "Ada Lovelace"
    w = pf.world(fix)
    sign_in_as(page, w, "ada", "/")
    for route in SIGNED_IN_ROUTES:
        goto(page, route)
        expect(tid(page, "current-user")).to_be_visible()
        expect(tid(page, "current-user")).to_contain_text("Ada Lovelace")
        assert_text(tid(page, "current-handle"), "ada")
        assert "@" not in tid(page, "current-handle").inner_text()


@L("R-238", "S-212", "S-213")
def test_logout_then_protected_screens_go_to_login(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    tid(page, "logout-button").click()
    expect(tid(page, "login-email")).to_be_visible(timeout=10000)
    expect(tid(page, "current-user")).to_have_count(0)
    for route in SIGNED_IN_ROUTES:
        page.goto(route)
        expect(tid(page, "login-email")).to_be_visible(timeout=10000)
        expect(tid(page, "current-user")).to_have_count(0)
        expect(tid(page, "current-handle")).to_have_count(0)
        assert not looks_like_json_page(page), f"{route} showed raw JSON after logout"


@L("S-213")
@pytest.mark.parametrize("route", SIGNED_IN_ROUTES)
def test_unauthenticated_visit_shows_login_not_json(page, route):
    pf.reset(plain_fixture())
    page.goto(route)
    expect(tid(page, "login-email")).to_be_visible(timeout=10000)
    assert not looks_like_json_page(page), f"{route} rendered raw JSON"
    expect(tid(page, "current-user")).to_have_count(0)


# ================================================================ wallet balance

@L("R-239", "R-243")
@pytest.mark.parametrize("cur,mu,minor,text", [
    ("EUR", 2, 10000, "100.00 EUR"), ("EUR", 2, 5, "0.05 EUR"), ("EUR", 2, 0, "0.00 EUR"),
    ("EUR", 2, 123456789, "1234567.89 EUR"),
    ("JPY", 0, 1200, "1200 JPY"), ("JPY", 0, 0, "0 JPY"), ("JPY", 0, 1000000, "1000000 JPY"),
    ("BHD", 3, 1250, "1.250 BHD"), ("BHD", 3, 7, "0.007 BHD"), ("BHD", 3, 0, "0.000 BHD"),
])
def test_wallet_balance_exact_text(page, cur, mu, minor, text):
    assert fmt(minor, mu, cur) == text
    w = pf.world(plain_fixture(cur, mu, balances=(minor, 2500, 500, 0)))
    sign_in_as(page, w, "ada", "/")
    bal = tid(page, "wallet-balance")
    assert_text(bal, text)
    expect(bal).to_have_attribute("data-amount", str(minor))


@L("S-207")
def test_held_and_messages_absent_when_none(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    assert_text(tid(page, "wallet-balance"), "100.00 EUR")
    for t in ("wallet-held", "pay-error", "pay-uncertain", "auth-error"):
        expect(tid(page, t)).to_have_count(0)   # absent from the DOM, not merely hidden


@L("S-207")
def test_held_present_with_seeded_hold(page):
    w = pf.world(pf2.fixture2(authorizations=[pf2.seed_auth("a_1", "u_ada", "u_bob", 2000)]))
    sign_in_as(page, w, "ada", "/")
    assert_text(tid(page, "wallet-held"), "20.00 EUR")
    expect(tid(page, "wallet-held")).to_have_attribute("data-amount", "2000")


# ================================================================ pay form

@L("R-240", "R-244", "R-246")
@pytest.mark.parametrize("typed,minor", [("15.00", 1500), ("15", 1500), ("15.5", 1550),
                                         ("0.01", 1)])
def test_pay_decimal_input_submits_minor_units(page, typed, minor):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", typed, "dinner", "public")
    resp = submit_and_response(page, "pay-submit", "/payments")
    assert resp.status == 201, resp.text()
    (post,) = page.rec.posts("/payments")
    assert body_of(post)["amount"] == minor and body_of(post)["to_handle"] == "bob"
    assert key_of(post), "POST /payments without Idempotency-Key"
    assert w.ada.balance() == 10000 - minor and w.bob.balance() == 2500 + minor
    assert_text(tid(page, "wallet-balance"), fmt(10000 - minor, 2, "EUR"))
    pid = resp.json()["payment_id"]
    expect(tid(page, f"activity-item-{pid}")).to_be_visible()
    expect(tid(page, "pay-error")).to_have_count(0)


@L("R-244")
@pytest.mark.parametrize("cur,mu,typed,minor", [
    ("JPY", 0, "15", 15), ("JPY", 0, "1200", 1200),
    ("BHD", 3, "1.25", 1250), ("BHD", 3, "1.250", 1250), ("BHD", 3, "0.001", 1),
])
def test_pay_decimal_other_currencies(page, cur, mu, typed, minor):
    w = pf.world(plain_fixture(cur, mu))
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", typed)
    resp = submit_and_response(page, "pay-submit", "/payments")
    assert resp.status == 201, resp.text()
    assert body_of(page.rec.posts("/payments")[0])["amount"] == minor
    assert w.ada.balance() == 10000 - minor


@L("R-240", "R-244")
@pytest.mark.parametrize("cur,mu,typed", [
    ("EUR", 2, "15.005"), ("EUR", 2, "abc"), ("EUR", 2, ""), ("EUR", 2, "0.001"),
    ("JPY", 0, "15.5"), ("JPY", 0, "15.0"), ("BHD", 3, "1.2505"),
])
def test_pay_bad_amount_shows_error_and_sends_nothing(page, cur, mu, typed):
    w = pf.world(plain_fixture(cur, mu))
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", typed)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-error")).to_be_visible()
    settle(page, 300)
    assert page.rec.posts("/payments") == [], "a request was sent for an invalid amount"
    assert w.ada.balance() == 10000


@L("D-213")
@pytest.mark.parametrize("typed", ["15.", ".5", "1e3", "-1", "1,5", "+1", "0x10"])
def test_pay_decimal_shapes_rejected_by_decision(page, typed):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", typed)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-error")).to_be_visible()
    settle(page, 300)
    assert page.rec.posts("/payments") == []


@L("R-240", "R-245")
def test_pay_private_with_note_reaches_feed(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "cy", "2.50", "rent 🏠", "private")
    resp = submit_and_response(page, "pay-submit", "/payments")
    assert resp.status == 201
    body = body_of(page.rec.posts("/payments")[0])
    assert body["visibility"] == "private" and body["note"] == "rent 🏠" \
        and body["to_handle"] == "cy" and body["amount"] == 250
    pid = resp.json()["payment_id"]
    expect(tid(page, f"activity-item-{pid}")).to_have_attribute("data-visibility", "private")
    assert_text(tid(page, f"activity-note-{pid}"), "rent 🏠")
    assert_text(tid(page, f"activity-amount-{pid}"), "2.50 EUR")
    assert [p["payment_id"] for p in w.bob.activity()] == [], "private leaked to third party"


@L("R-240", "S-203")
@pytest.mark.parametrize("handle,code", [("ghost", "not_found"), ("ada", "self_payment")])
def test_pay_refused_by_server_shows_pay_error(page, handle, code):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, handle, "1.00")
    resp = submit_and_response(page, "pay-submit", "/payments")
    assert resp.status in (404, 422) and resp.json()["error"]["code"] == code
    expect(tid(page, "pay-error")).to_be_visible()
    expect(tid(page, "pay-uncertain")).to_have_count(0)
    assert w.ada.balance() == 10000


# ================================================================ double submit / keys

@L("R-242", "I-205", "D-209")
def test_double_submit_unchanged_form_moves_money_once(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", "15.00", "dinner", "public")
    r1 = submit_and_response(page, "pay-submit", "/payments")
    assert r1.status == 201
    assert_text(tid(page, "wallet-balance"), "85.00 EUR")
    assert pay_values(page) == ("bob", "15.00", "dinner", "public"), "form not kept"
    items_before = len(dom_testids(page, "activity-list", "activity-item-"))
    r2 = submit_and_response(page, "pay-submit", "/payments")
    assert r2.status == 200, f"resubmit must be a replay, got {r2.status}"
    posts = page.rec.posts("/payments")
    assert len(posts) == 2, f"expected 2 POSTs (D-209 replay), got {len(posts)}"
    assert key_of(posts[0]) == key_of(posts[1]), "resubmit used a new Idempotency-Key"
    assert body_of(posts[0]) == body_of(posts[1])
    settle(page)
    assert_text(tid(page, "wallet-balance"), "85.00 EUR")
    expect(tid(page, "pay-error")).to_have_count(0)
    assert len(dom_testids(page, "activity-list", "activity-item-")) == items_before
    assert w.ada.balance() == 8500 and w.bob.balance() == 4000
    assert len(ids_of(w.ada, "dinner")) == 1


@L("R-242", "I-205")
def test_rapid_double_click_moves_money_once(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", "15.00", "fast", "public")
    tid(page, "pay-submit").dblclick()
    assert_text(tid(page, "wallet-balance"), "85.00 EUR")
    settle(page, 600)
    keys = {key_of(e) for e in page.rec.posts("/payments")}
    assert len(keys) == 1, f"double click used several keys: {keys}"
    assert w.ada.balance() == 8500 and len(ids_of(w.ada, "fast")) == 1
    expect(tid(page, "pay-error")).to_have_count(0)


@L("R-242", "S-202", "D-209")
@pytest.mark.parametrize("field,value,to,minor", [
    ("pay-handle", "cy", "cy", 1500), ("pay-amount", "16", "bob", 1600),
    ("pay-note", "dinner 2", "bob", 1500), ("pay-visibility", "private", "bob", 1500),
])
def test_changing_one_field_mints_new_key(page, field, value, to, minor):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", "15.00", "dinner", "public")
    assert submit_and_response(page, "pay-submit", "/payments").status == 201
    assert_text(tid(page, "wallet-balance"), "85.00 EUR")
    if field == "pay-visibility":
        tid(page, field).select_option(value)
    else:
        set_value(tid(page, field), value)
    r2 = submit_and_response(page, "pay-submit", "/payments")
    assert r2.status == 201, f"changed form must be a new payment, got {r2.status}"
    p1, p2 = page.rec.posts("/payments")
    assert key_of(p1) != key_of(p2), "changed field reused the key"
    assert w.ada.balance() == 10000 - 1500 - minor
    assert_text(tid(page, "wallet-balance"), fmt(10000 - 1500 - minor, 2, "EUR"))
    assert r2.json()["to_handle"] == to


@L("S-202")
def test_refused_then_changed_amount_gets_new_key(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "cy", "/")
    fill_pay(page, "bob", "6.00", "x")
    assert submit_and_response(page, "pay-submit", "/payments").status == 409
    expect(tid(page, "pay-error")).to_be_visible()
    set_value(tid(page, "pay-amount"), "5.00")
    assert submit_and_response(page, "pay-submit", "/payments").status == 201
    p1, p2 = page.rec.posts("/payments")
    assert key_of(p1) != key_of(p2)
    expect(tid(page, "pay-error")).to_have_count(0)
    assert w.cy.balance() == 0


# ================================================================ insufficient funds

@L("R-248", "R-240")
def test_insufficient_funds_keeps_inputs_and_refreshes(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "cy", "/")
    assert_text(tid(page, "wallet-balance"), "5.00 EUR")
    fill_pay(page, "bob", "5.00", "all of it", "private")
    other = ok(w.cy.pay("dee", 100, note="elsewhere"), 201)   # another client spends
    resp = submit_and_response(page, "pay-submit", "/payments")
    assert resp.status == 409 and resp.json()["error"]["code"] == "insufficient_funds"
    expect(tid(page, "pay-error")).to_be_visible()
    expect(tid(page, "pay-uncertain")).to_have_count(0)
    assert pay_values(page) == ("bob", "5.00", "all of it", "private")
    assert_text(tid(page, "wallet-balance"), "4.00 EUR")
    expect(tid(page, f"activity-item-{other['payment_id']}")).to_be_visible()
    assert w.cy.balance() == 400 and w.bob.balance() == 2500


@L("R-248")
def test_affordable_payment_shows_no_error(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "cy", "/")
    fill_pay(page, "bob", "5.00")
    assert submit_and_response(page, "pay-submit", "/payments").status == 201
    expect(tid(page, "pay-error")).to_have_count(0)
    assert_text(tid(page, "wallet-balance"), "0.00 EUR")
    assert w.cy.balance() == 0


# ================================================================ request form

@L("R-241", "R-244")
@pytest.mark.parametrize("typed,minor", [("12.00", 1200), ("12", 1200), ("12.5", 1250)])
def test_request_form_creates_request(page, typed, minor):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_request(page, "bob", typed, "taxi")
    resp = submit_and_response(page, "request-submit", "/requests")
    assert resp.status == 201, resp.text()
    body = body_of(page.rec.posts("/requests")[0])
    assert body["payer_handle"] == "bob" and body["amount"] == minor
    assert key_of(page.rec.posts("/requests")[0])
    expect(tid(page, "request-error")).to_have_count(0)
    got = [q for q in w.bob.requests("direction=incoming") if q["note"] == "taxi"]
    assert len(got) == 1 and got[0]["amount"] == minor and got[0]["status"] == "pending"
    assert got[0]["requester_handle"] == "ada"


@L("R-241")
@pytest.mark.parametrize("handle,typed,sends", [("ghost", "12.00", True),
                                                ("ada", "12.00", True),
                                                ("bob", "12.005", False),
                                                ("bob", "abc", False)])
def test_request_refused_shows_request_error(page, handle, typed, sends):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_request(page, handle, typed, "nope")
    tid(page, "request-submit").click()
    expect(tid(page, "request-error")).to_be_visible()
    settle(page, 300)
    assert bool(page.rec.posts("/requests")) == sends
    assert [q for q in w.ada.requests() if q["note"] == "nope"] == []


# ================================================================ activity feed

@L("R-245")
def test_feed_newest_first_and_item_contents(page):
    w = pf.world(plain_fixture())
    p1 = ok(w.ada.pay("bob", 100, note="first"), 201)
    time.sleep(1.1)
    p2 = ok(w.ada.pay("cy", 205, note="", visibility="private"), 201)
    time.sleep(1.1)
    p3 = ok(w.bob.pay("ada", 7, note="third ✓"), 201)
    sign_in_as(page, w, "ada", "/")
    expect(tid(page, f"activity-item-{p1['payment_id']}")).to_be_visible()
    order = dom_testids(page, "activity-list", "activity-item-")
    assert order == [p3["payment_id"], p2["payment_id"], p1["payment_id"]], order
    for p, vis, a, b, amount, note in [(p1, "public", "ada", "bob", "1.00 EUR", "first"),
                                       (p2, "private", "ada", "cy", "2.05 EUR", ""),
                                       (p3, "public", "bob", "ada", "0.07 EUR", "third ✓")]:
        i = p["payment_id"]
        expect(tid(page, f"activity-item-{i}")).to_have_attribute("data-visibility", vis)
        parties = tid(page, f"activity-parties-{i}").inner_text()
        assert a in parties and b in parties, parties
        assert_text(tid(page, f"activity-amount-{i}"), amount)
        expect(tid(page, f"activity-note-{i}")).to_have_count(1)  # present even when empty
        assert tid(page, f"activity-note-{i}").inner_text().strip() == note
    expect(tid(page, "empty-activity")).to_have_count(0)


@L("R-245")
def test_feed_visibility_rule_in_ui(browser):
    w = pf.world(pf.fixture())   # p_1 ada->bob public, p_2 bob->cy private
    for handle, p2_shown in (("ada", False), ("dee", False), ("cy", True), ("bob", True)):
        pg = new_page(browser)
        try:
            sign_in_as(pg, w, handle, "/")
            expect(tid(pg, "activity-item-p_1")).to_have_attribute("data-visibility", "public")
            if p2_shown:
                expect(tid(pg, "activity-item-p_2")).to_have_attribute("data-visibility",
                                                                       "private")
            else:   # others' private payments are not shown at all
                expect(tid(pg, "activity-item-p_2")).to_have_count(0)
        finally:
            close_page(pg)


@L("R-245")
def test_feed_shows_every_visible_payment_beyond_one_page(page):
    """One activity item per visible payment, also past 50 and past 200 (pagination)."""
    fix = plain_fixture()
    fix["payments"] = [{"id": f"p_{i}", "from_user_id": "u_ada", "to_user_id": "u_bob",
                        "amount": 1, "note": f"n{i}", "visibility": "public"}
                       for i in range(230)]
    w = pf.world(fix)
    sign_in_as(page, w, "dee", "/")
    expect(tid(page, "activity-item-p_0")).to_have_count(1, timeout=10000)
    expect(page.locator("[data-testid^='activity-item-']")).to_have_count(230, timeout=10000)


@L("R-245")
def test_empty_activity_then_first_item(page):
    fix = plain_fixture()
    fix["payments"] = [pf.SEED_PAYMENTS[1]]   # bob->cy private: invisible to dee
    w = pf.world(fix)
    sign_in_as(page, w, "dee", "/")
    expect(tid(page, "empty-activity")).to_be_visible()
    expect(page.locator("[data-testid^='activity-item-']")).to_have_count(0)
    p = ok(w.ada.pay("dee", 300, note="welcome"), 201)
    tid(page, "wallet-refresh").click()
    expect(tid(page, f"activity-item-{p['payment_id']}")).to_be_visible()
    expect(tid(page, "empty-activity")).to_have_count(0)
    assert_text(tid(page, "wallet-balance"), "3.00 EUR")


# ================================================================ refresh

@L("R-246")
def test_action_refresh_waits_for_write(page):
    """The POST is held unsent; data shown afterwards must include the write."""
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    hold = Hold(page, {"/payments"}, method="POST", snapshot=False)
    hold.arm()
    fill_pay(page, "bob", "15.00", "held write")
    tid(page, "pay-submit").click()
    hold.wait_held(1)
    settle(page, 500)
    assert w.ada.balance() == 10000, "write reached the server while held?"
    hold.disarm()
    hold.release()
    assert_text(tid(page, "wallet-balance"), "85.00 EUR", timeout=8000)
    (pid,) = ids_of(w.ada, "held write")
    expect(tid(page, f"activity-item-{pid}")).to_be_visible()


@L("R-247", "R-250")
def test_wallet_refresh_keeps_form_and_picks_up_other_client(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    assert_text(tid(page, "wallet-balance"), "100.00 EUR")
    fill_pay(page, "cy", "3.21", "typed but not sent", "private")
    p = ok(w.bob.pay("ada", 500, note="from bob"), 201)
    # no live update required (R-250): only the explicit refresh must show it
    tid(page, "wallet-refresh").click()
    assert_text(tid(page, "wallet-balance"), "105.00 EUR")
    expect(tid(page, f"activity-item-{p['payment_id']}")).to_be_visible()
    assert pay_values(page) == ("cy", "3.21", "typed but not sent", "private")
    assert page.rec.posts("/payments") == []
    assert not page.errors, page.errors


@L("R-247")
def test_wallet_refresh_updates_available_and_held(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    expect(tid(page, "wallet-held")).to_have_count(0)
    ok(pf2.authorize(w.ada, "bob", 1000), 201)
    tid(page, "wallet-refresh").click()
    assert_text(tid(page, "wallet-available"), "90.00 EUR")
    assert_text(tid(page, "wallet-held"), "10.00 EUR")
    assert_text(tid(page, "wallet-balance"), "100.00 EUR")


@L("R-247")
def test_latest_refresh_wins_out_of_order(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    assert_text(tid(page, "wallet-balance"), "100.00 EUR")
    hold = Hold(page, {"/me", "/activity"}, snapshot=True)
    hold.arm()
    tid(page, "wallet-refresh").click()          # refresh #1: answers captured at 100.00
    hold.wait_held(1)
    settle(page, 300)                            # let its parallel read be held too
    p = ok(w.bob.pay("ada", 500, note="newer"), 201)
    hold.disarm()
    tid(page, "wallet-refresh").click()          # refresh #2: live, 105.00
    assert_text(tid(page, "wallet-balance"), "105.00 EUR")
    expect(tid(page, f"activity-item-{p['payment_id']}")).to_be_visible()
    hold.release()                               # stale #1 arrives last
    settle(page, 700)
    assert_text(tid(page, "wallet-balance"), "105.00 EUR", timeout=100)
    expect(tid(page, f"activity-item-{p['payment_id']}")).to_be_visible(timeout=100)
    expect(tid(page, "wallet-balance")).to_have_attribute("data-amount", "10500", timeout=100)


@L("R-247", "R-246")
def test_stale_refresh_does_not_overwrite_post_action_refresh(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    assert_text(tid(page, "wallet-balance"), "100.00 EUR")
    hold = Hold(page, {"/me", "/activity"}, snapshot=True)
    hold.arm()
    tid(page, "wallet-refresh").click()          # stale read at 100.00
    hold.wait_held(1)
    settle(page, 300)
    hold.disarm()
    fill_pay(page, "bob", "15.00", "after stale")
    assert submit_and_response(page, "pay-submit", "/payments").status == 201
    assert_text(tid(page, "wallet-balance"), "85.00 EUR")
    hold.release()
    settle(page, 700)
    assert_text(tid(page, "wallet-balance"), "85.00 EUR", timeout=100)


# ================================================================ lost responses

@L("R-249", "S-203")
def test_lost_response_after_commit_then_retry_recovers(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", "15.00", "lost", "public")
    lose = commit_then_lose(page)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-uncertain")).to_be_visible()
    assert tid(page, "pay-uncertain").inner_text().strip(), "pay-uncertain has no text"
    expect(tid(page, "pay-error")).to_have_count(0)
    assert lose.results and lose.results[0]["status"] == 201, lose.results
    assert w.ada.balance() == 8500                     # the server did commit
    assert pay_values(page) == ("bob", "15.00", "lost", "public")
    lose.remove()
    r2 = submit_and_response(page, "pay-submit", "/payments")
    assert r2.status == 200, f"retry should replay the committed payment, got {r2.status}"
    p1, p2 = page.rec.posts("/payments")
    assert key_of(p1) == key_of(p2) and body_of(p1) == body_of(p2)
    expect(tid(page, "pay-uncertain")).to_have_count(0)
    expect(tid(page, "pay-error")).to_have_count(0)
    assert_text(tid(page, "wallet-balance"), "85.00 EUR")
    (pid,) = ids_of(w.ada, "lost")
    expect(tid(page, f"activity-item-{pid}")).to_be_visible()
    assert w.ada.balance() == 8500 and w.bob.balance() == 4000


@L("R-249", "S-203")
def test_network_failure_before_server_then_retry_commits_once(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", "15.00", "never arrived")
    lose = lose_before_server(page)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-uncertain")).to_be_visible()
    assert tid(page, "pay-uncertain").inner_text().strip()
    expect(tid(page, "pay-error")).to_have_count(0)
    assert w.ada.balance() == 10000
    lose.remove()
    r2 = submit_and_response(page, "pay-submit", "/payments")
    assert r2.status == 201, r2.status
    p1, p2 = page.rec.posts("/payments")
    assert key_of(p1) == key_of(p2) and body_of(p1) == body_of(p2)
    expect(tid(page, "pay-uncertain")).to_have_count(0)
    assert_text(tid(page, "wallet-balance"), "85.00 EUR")
    assert w.ada.balance() == 8500 and len(ids_of(w.ada, "never arrived")) == 1


@L("S-203", "R-249")
def test_bodyless_5xx_after_commit_is_uncertain(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "ada", "/")
    fill_pay(page, "bob", "15.00", "gateway")
    lose = LoseResponses(page, "/payments", commit=True, status=502)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-uncertain")).to_be_visible()
    expect(tid(page, "pay-error")).to_have_count(0)
    lose.remove()
    assert submit_and_response(page, "pay-submit", "/payments").status == 200
    expect(tid(page, "pay-uncertain")).to_have_count(0)
    assert w.ada.balance() == 8500 and len(ids_of(w.ada, "gateway")) == 1


@L("S-203")
def test_confirmed_4xx_is_error_not_uncertain(page):
    w = pf.world(plain_fixture())
    sign_in_as(page, w, "dee", "/")
    fill_pay(page, "bob", "1.00")
    assert submit_and_response(page, "pay-submit", "/payments").status == 409
    expect(tid(page, "pay-error")).to_be_visible()
    expect(tid(page, "pay-uncertain")).to_have_count(0)
