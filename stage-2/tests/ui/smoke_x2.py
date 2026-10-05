"""Headless smoke for X2 against a running server (BASE env). Prints PASS/FAIL per check."""
# Needs Playwright and a running server: BASE=http://127.0.0.1:<port> python <this file>
import json
import os
import sys
import urllib.request

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("BASE", "http://127.0.0.1:18291")
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def reset():
    fixture = {
        "currency": "EUR", "minor_units": 2,
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
             "display_name": "Ada Lovelace", "handle": "ada", "balance": 10000},
            {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
             "display_name": "Bob", "handle": "bob", "balance": 2500},
        ],
        "payments": [], "requests": [],
    }
    req = urllib.request.Request(BASE + "/_test/reset", data=json.dumps(fixture).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def tid(page, name):
    return page.get_by_test_id(name)


def money(page, name):
    return tid(page, name).inner_text()


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    reset()
    for width in (375, 1280):
        page = browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/")
        page.wait_for_url("**/login")
        check(f"[{width}] unauthenticated / redirects to /login", page.url.endswith("/login"))
        tid(page, "login-email").fill("ada@example.com")
        tid(page, "login-password").fill("wrong password")
        tid(page, "login-submit").click()
        expect(tid(page, "auth-error")).to_be_visible()
        check(f"[{width}] auth-error on wrong password", tid(page, "auth-error").count() == 1)
        tid(page, "login-password").fill("correct horse")
        tid(page, "login-submit").click()
        page.wait_for_url(BASE + "/")
        expect(tid(page, "wallet-balance")).to_be_visible()
        check(f"[{width}] current-user has display name", "Ada Lovelace" in tid(page, "current-user").inner_text())
        check(f"[{width}] current-handle exact", tid(page, "current-handle").inner_text() == "ada")
        check(f"[{width}] wallet-balance formatted", money(page, "wallet-balance") == "100.00 EUR")
        check(f"[{width}] wallet-balance data-amount", tid(page, "wallet-balance").get_attribute("data-amount") == "10000")
        check(f"[{width}] wallet-held absent at zero", tid(page, "wallet-held").count() == 0)
        check(f"[{width}] no pay-error/uncertain initially",
              tid(page, "pay-error").count() == 0 and tid(page, "pay-uncertain").count() == 0)
        check(f"[{width}] no horizontal scroll",
              page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        check(f"[{width}] no JS errors", not errors)
        if width == 375:
            page.close()
            continue

        # Pay 15.00, then resubmit unchanged: money moves once.
        tid(page, "pay-handle").fill("bob")
        tid(page, "pay-amount").fill("15")
        tid(page, "pay-note").fill("lunch 🍜")
        tid(page, "pay-visibility").select_option("private")
        tid(page, "pay-submit").click()
        expect(tid(page, "wallet-balance")).to_have_text("85.00 EUR")
        items = page.locator('[data-testid^="activity-item-"]')
        check("pay: one activity item", items.count() == 1)
        pid = items.first.get_attribute("data-testid").removeprefix("activity-item-")
        check("activity data-visibility private", items.first.get_attribute("data-visibility") == "private")
        check("activity amount exact", money(page, f"activity-amount-{pid}") == "15.00 EUR")
        check("activity note exact", tid(page, f"activity-note-{pid}").inner_text() == "lunch 🍜")
        parties = tid(page, f"activity-parties-{pid}").inner_text()
        check("activity parties has both handles", "ada" in parties and "bob" in parties)
        check("pay form keeps values", tid(page, "pay-amount").input_value() == "15")
        tid(page, "pay-submit").click()
        page.wait_for_timeout(700)
        check("resubmit unchanged: balance fell once", money(page, "wallet-balance") == "85.00 EUR")
        check("resubmit unchanged: still one item", items.count() == 1)
        check("resubmit unchanged: no pay-error", tid(page, "pay-error").count() == 0)
        # Changing a field makes a new payment.
        tid(page, "pay-amount").fill("15.5")
        tid(page, "pay-submit").click()
        expect(tid(page, "wallet-balance")).to_have_text("69.50 EUR")
        check("changed field: new payment", items.count() == 2)
        # Invalid amounts never send a request.
        sent = []
        page.on("request", lambda r: sent.append(r.url) if r.url.endswith("/payments") else None)
        for bad in ("15.005", "abc", "1e3", ".5"):
            tid(page, "pay-amount").fill(bad)
            tid(page, "pay-submit").click()
            expect(tid(page, "pay-error")).to_be_visible()
        check("invalid amounts: pay-error and no request", not sent)
        # Insufficient funds: pay-error, inputs kept.
        tid(page, "pay-amount").fill("1000")
        tid(page, "pay-submit").click()
        expect(tid(page, "pay-error")).to_be_visible()
        check("insufficient: pay-error, inputs kept",
              tid(page, "pay-amount").input_value() == "1000" and tid(page, "pay-handle").input_value() == "bob")
        # Lost response after commit: pay-uncertain, then retry moves money once.
        tid(page, "pay-amount").fill("1.00")
        state = {"dropped": False}

        def drop_once(route):
            if not state["dropped"]:
                state["dropped"] = True
                route.fetch()      # reaches the server and commits
                route.abort()      # but the browser never sees the response
            else:
                route.continue_()
        page.route("**/payments", drop_once)
        tid(page, "pay-submit").click()
        expect(tid(page, "pay-uncertain")).to_be_visible()
        check("lost response: pay-uncertain, not pay-error", tid(page, "pay-error").count() == 0)
        tid(page, "pay-submit").click()
        expect(tid(page, "pay-uncertain")).to_have_count(0)
        expect(tid(page, "wallet-balance")).to_have_text("68.50 EUR")
        check("retry after lost response: moved once", money(page, "wallet-balance") == "68.50 EUR"
              and tid(page, "pay-error").count() == 0)
        page.unroute("**/payments")
        # Request form.
        tid(page, "request-handle").fill("bob")
        tid(page, "request-amount").fill("3.25")
        tid(page, "request-submit").click()
        page.wait_for_timeout(500)
        check("request created without error", tid(page, "request-error").count() == 0)
        tid(page, "request-handle").fill("ada")
        tid(page, "request-submit").click()
        expect(tid(page, "request-error")).to_be_visible()
        check("self request refused", tid(page, "request-error").count() == 1)
        # Refresh keeps the pay form.
        tid(page, "pay-note").fill("draft")
        tid(page, "wallet-refresh").click()
        page.wait_for_timeout(300)
        check("refresh keeps pay form", tid(page, "pay-note").input_value() == "draft")
        # Logout.
        tid(page, "logout-button").click()
        page.wait_for_url("**/login")
        page.goto(BASE + "/")
        page.wait_for_url("**/login")
        check("after logout / goes to login", tid(page, "current-user").count() == 0)
        check("no JS errors (desktop)", not errors)
        page.close()
    browser.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
