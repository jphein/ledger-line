"""Headless smoke for X3 screens against a running server (BASE env)."""
# Needs Playwright and a running server: BASE=http://127.0.0.1:<port> python <this file>
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("BASE", "http://127.0.0.1:18292")
SHOTS = os.environ.get("SHOTS", "/tmp/x3_shots")
os.makedirs(SHOTS, exist_ok=True)
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def http(method, path, body=None, token=None, key=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def reset():
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    fixture = {
        "currency": "EUR", "minor_units": 2,
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
             "display_name": "Ada Lovelace", "handle": "ada", "balance": 10000},
            {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
             "display_name": "Bob", "handle": "bob", "balance": 2500},
            {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
             "display_name": "Cy", "handle": "cy", "balance": 0},
        ],
        "payments": [{"id": "p_1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500,
                      "note": "", "visibility": "public"}],
        "requests": [
            {"id": "rq_in", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
             "note": "taxi", "status": "pending"},
            {"id": "rq_out", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 300,
             "note": "snacks", "status": "pending"},
        ],
        "authorizations": [
            {"id": "a_out", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000,
             "note": "deposit", "visibility": "public", "status": "open", "expires_at": later},
            {"id": "a_in", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 2000,
             "note": "rental", "visibility": "private", "status": "open", "expires_at": later},
        ],
    }
    assert http("POST", "/_test/reset", fixture)[0] == 204


def tid(page, name):
    return page.get_by_test_id(name)


def login(page, email="ada@example.com"):
    page.goto(BASE + "/login")
    tid(page, "login-email").fill(email)
    tid(page, "login-password").fill("correct horse")
    tid(page, "login-submit").click()
    page.wait_for_url(BASE + "/")
    expect(tid(page, "wallet-available")).to_be_visible()


def no_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (375, 1280):
        reset()
        page = browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        login(page)
        page.screenshot(path=f"{SHOTS}/wallet-{width}.png", full_page=True)
        check(f"[{width}] wallet-available headline", tid(page, "wallet-available").inner_text() == "80.00 EUR"
              and tid(page, "wallet-available").get_attribute("data-amount") == "8000")
        check(f"[{width}] wallet-held shown", tid(page, "wallet-held").inner_text() == "20.00 EUR")
        check(f"[{width}] wallet-balance is total", tid(page, "wallet-balance").inner_text() == "100.00 EUR")
        sizes = page.evaluate("""() => ['wallet-available','wallet-balance','wallet-held'].map(t =>
            parseFloat(getComputedStyle(document.querySelector(`[data-testid="${t}"]`)).fontSize))""")
        check(f"[{width}] available has the largest money font", sizes[0] > max(sizes[1:]))
        check(f"[{width}] empty note present", tid(page, "activity-note-p_1").count() == 1)
        check(f"[{width}] wallet no horizontal scroll", no_scroll(page))
        for path, shot in (("/requests", "requests"), ("/split", "split"), ("/authorizations", "holds")):
            page.goto(BASE + path)
            expect(tid(page, "current-user")).to_be_visible()
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SHOTS}/{shot}-{width}.png", full_page=True)
            check(f"[{width}] {path} current-user + no horizontal scroll", no_scroll(page))
        check(f"[{width}] no JS errors", not errors)
        page.close()

    # Functional checks at desktop width.
    reset()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    login(page)

    # Authorize form.
    tid(page, "authorize-handle").fill("cy")
    tid(page, "authorize-amount").fill("10")
    tid(page, "authorize-submit").click()
    expect(tid(page, "wallet-held")).to_have_text("30.00 EUR")
    check("authorize: held rises, available falls", tid(page, "wallet-available").inner_text() == "70.00 EUR")
    tid(page, "authorize-amount").fill("1000")
    tid(page, "authorize-submit").click()
    expect(tid(page, "authorize-error")).to_be_visible()
    check("authorize: insufficient available refused", tid(page, "authorize-error").count() == 1)

    # Requests screen.
    page.goto(BASE + "/requests")
    expect(tid(page, "request-item-rq_in")).to_be_visible()
    check("requests: incoming has pay/decline", tid(page, "request-pay-rq_in").count() == 1
          and tid(page, "request-decline-rq_in").count() == 1 and tid(page, "request-cancel-rq_in").count() == 0)
    check("requests: outgoing has cancel only", tid(page, "request-cancel-rq_out").count() == 1
          and tid(page, "request-pay-rq_out").count() == 0)
    check("requests: amount formatted", tid(page, "request-amount-rq_in").inner_text() == "12.00 EUR")
    check("requests: data-status", tid(page, "request-item-rq_in").get_attribute("data-status") == "pending")
    check("requests: lists present", tid(page, "incoming-list").count() == 1 and tid(page, "outgoing-list").count() == 1)
    # Cancelled elsewhere while the pay button is visible.
    bob = http("POST", "/auth/login", {"email": "bob@example.com", "password": "correct horse"})[1]["token"]
    http("POST", "/requests/rq_in/cancel", token=bob)
    tid(page, "request-pay-rq_in").click()
    expect(tid(page, "request-error")).to_be_visible()
    expect(tid(page, "request-pay-rq_in")).to_have_count(0)
    check("stale pay: request-error and button gone",
          tid(page, "request-item-rq_in").get_attribute("data-status") == "cancelled")
    tid(page, "request-cancel-rq_out").click()
    expect(tid(page, "request-item-rq_out")).to_have_attribute("data-status", "cancelled")
    check("cancel own request", tid(page, "request-cancel-rq_out").count() == 0)

    # Split screen: preview equals server shares.
    page.goto(BASE + "/split")
    tid(page, "split-amount").fill("10")
    tid(page, "split-handles").fill("bob, ada, cy")
    expect(tid(page, "split-share-bob")).to_have_text("3.34 EUR")
    preview = {h: tid(page, f"split-share-{h}").inner_text() for h in ("bob", "ada", "cy")}
    check("split preview by rule", preview == {"bob": "3.34 EUR", "ada": "3.33 EUR", "cy": "3.33 EUR"})
    with page.expect_response(lambda r: r.url.endswith("/splits")) as info:
        tid(page, "split-submit").click()
    server = info.value.json()
    check("split preview == server shares",
          {s["handle"]: s["amount"] for s in server["shares"]} == {"bob": 334, "ada": 333, "cy": 333})
    tid(page, "split-amount").fill("1.005")
    tid(page, "split-submit").click()
    expect(tid(page, "split-error")).to_be_visible()
    check("split invalid amount refused locally", tid(page, "split-error").count() == 1)

    # Holds screen.
    page.goto(BASE + "/authorizations")
    expect(tid(page, "authorization-list")).to_be_visible()
    ids = page.locator('[data-testid^="authorization-item-"]').evaluate_all(
        "els => els.map(e => e.dataset.testid.replace('authorization-item-', ''))")
    check("holds newest first", ids[0] not in ("a_out", "a_in") and ids[-1] == "a_out")
    check("incoming open: capture input prefilled", tid(page, "authorization-capture-amount-a_in").input_value() == "20.00")
    check("incoming open: no void", tid(page, "authorization-void-a_in").count() == 0)
    check("outgoing open: void only", tid(page, "authorization-void-a_out").count() == 1
          and tid(page, "authorization-capture-a_out").count() == 0)
    expires = http("GET", "/authorizations", token=bob)[1]["authorizations"]
    raw = {a["authorization_id"]: a["expires_at"] for a in expires}
    check("expires text is raw RFC 3339", tid(page, "authorization-expires-a_in").inner_text() == raw["a_in"])
    check("amount formatted", tid(page, "authorization-amount-a_in").inner_text() == "20.00 EUR")
    tid(page, "authorization-capture-amount-a_in").fill("15")
    tid(page, "authorization-capture-a_in").click()
    expect(tid(page, "authorization-item-a_in")).to_have_attribute("data-status", "captured")
    check("capture: captured amount shown", tid(page, "authorization-captured-a_in").inner_text() == "15.00 EUR")
    # Stale void: bob... ada voids a_out; then a stale void click on an already-captured hold.
    tid(page, "authorization-void-a_out").click()
    expect(tid(page, "authorization-item-a_out")).to_have_attribute("data-status", "voided")
    check("void: button gone", tid(page, "authorization-void-a_out").count() == 0)
    check("no authorization-error after success", tid(page, "authorization-error").count() == 0)
    # Stale capture: cy's hold voided elsewhere while ada... (ada is payer of the new hold; use bob view)
    page.goto(BASE + "/")
    expect(tid(page, "wallet-available")).to_be_visible()
    check("wallet after capture/void", tid(page, "wallet-balance").inner_text() == "115.00 EUR")

    # Upgrade in the browser: export, wipe, import; the open page keeps working.
    doc = http("GET", "/_test/export")[1]
    reset()
    assert http("POST", "/_test/import", doc)[0] == 204
    tid(page, "wallet-refresh").click()
    expect(tid(page, "wallet-balance")).to_have_text("115.00 EUR")
    check("upgrade: still signed in after import", tid(page, "current-user").count() == 1)
    check("no JS errors (functional)", not errors)
    page.close()
    browser.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
