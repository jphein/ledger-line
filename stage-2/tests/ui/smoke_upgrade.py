"""S-204 / R-232 in the browser: a payment whose response is lost before an
export/import upgrade is retried after import with the same key and body; the UI
recovers the original payment and shows the imported balance, without a reload.

Needs Playwright and a running server: BASE=http://127.0.0.1:<port> python smoke_upgrade.py
"""
import json
import os
import sys
import urllib.request

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("BASE", "http://127.0.0.1:8080")
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def http(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        return resp.status, json.loads(raw) if raw else None


fixture = {"currency": "EUR", "minor_units": 2, "users": [
    {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
     "display_name": "Ada", "handle": "ada", "balance": 10000},
    {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
     "display_name": "Bob", "handle": "bob", "balance": 2500}]}
other = {"currency": "JPY", "minor_units": 0, "users": [
    {"id": "u_zed", "email": "zed@example.com", "password": "correct horse",
     "display_name": "Zed", "handle": "zed", "balance": 1}]}

with sync_playwright() as pw:
    page = pw.chromium.launch().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    http("POST", "/_test/reset", fixture)
    page.goto(BASE + "/login")
    page.get_by_test_id("login-email").fill("ada@example.com")
    page.get_by_test_id("login-password").fill("correct horse")
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(BASE + "/")
    tid = page.get_by_test_id
    tid("pay-handle").fill("bob")
    tid("pay-amount").fill("12.34")
    tid("pay-note").fill("before upgrade")

    sent = []
    dropped = {"done": False}

    def drop_once(route):
        sent.append((route.request.headers.get("idempotency-key"), route.request.post_data))
        if not dropped["done"]:
            dropped["done"] = True
            route.fetch()   # the payment commits on the server
            route.abort()   # but its response is lost
        else:
            route.continue_()

    page.route("**/payments", drop_once)
    tid("pay-submit").click()
    expect(tid("pay-uncertain")).to_be_visible()
    check("lost response shows pay-uncertain", tid("pay-error").count() == 0)

    # Upgrade between browser requests: export, wipe with another fixture, import.
    status, doc = http("GET", "/_test/export")
    http("POST", "/_test/reset", other)
    check("import accepted", http("POST", "/_test/import", doc)[0] == 204)

    # Retry the unchanged form: same key and body, original payment recovered.
    with page.expect_response(lambda r: r.url.endswith("/payments")) as info:
        tid("pay-submit").click()
    check("retry is a 200 replay", info.value.status == 200)
    check("retry reused key and body", len(sent) == 2 and sent[0] == sent[1])
    expect(tid("pay-uncertain")).to_have_count(0)
    expect(tid("wallet-balance")).to_have_text("87.66 EUR")
    check("balance shows the imported state, money moved once",
          tid("wallet-balance").inner_text() == "87.66 EUR")
    items = page.locator('[data-testid^="activity-item-"]')
    check("one payment in the feed", items.count() == 1)
    check("still signed in, no reload", tid("current-user").inner_text() == "Ada")
    check("no pay-error", tid("pay-error").count() == 0)
    check("no JS errors", not errors)

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
