"""Lists render every item beyond one 200-item page (R-245, R-251, R-257)."""
# Needs Playwright and a running server: BASE=http://127.0.0.1:<port> python <this file>
import json, os, sys, urllib.request
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright, expect
BASE = os.environ["BASE"]
later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
users = [{"id": f"u_{h}", "email": f"{h}@example.com", "password": "correct horse",
          "display_name": h.title(), "handle": h, "balance": 100000} for h in ("ada", "bob", "cy")]
fixture = {"currency": "JPY", "minor_units": 0, "users": users,
           "payments": [{"id": f"p_{i}", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 1,
                         "note": "", "visibility": "public"} for i in range(260)],
           "requests": [{"id": f"rq_{i}", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 2,
                         "status": "pending"} for i in range(230)],
           "authorizations": [{"id": f"a_{i}", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1,
                               "status": "open", "expires_at": later} for i in range(210)]}
req = urllib.request.Request(BASE + "/_test/reset", data=json.dumps(fixture).encode(), method="POST")
urllib.request.urlopen(req, timeout=20).read()
ok = True
with sync_playwright() as pw:
    page = pw.chromium.launch().new_page()
    page.goto(BASE + "/login")
    page.get_by_test_id("login-email").fill("ada@example.com")
    page.get_by_test_id("login-password").fill("correct horse")
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(BASE + "/")
    for path, prefix, n in (("/", "activity-item-", 260), ("/requests", "request-item-", 230),
                            ("/authorizations", "authorization-item-", 210)):
        if path != "/":
            page.goto(BASE + path)
        expect(page.locator(f'[data-testid^="{prefix}"]')).to_have_count(n, timeout=15000)
        got = page.locator(f'[data-testid^="{prefix}"]').count()
        print(("PASS" if got == n else "FAIL"), path, got, "of", n)
        ok &= got == n
    print("JPY format:", page.goto(BASE + "/") and page.get_by_test_id("wallet-balance").inner_text())
sys.exit(0 if ok else 1)
