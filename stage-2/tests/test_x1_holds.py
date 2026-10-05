"""X1: holds, authorizations, captures, voids, expiry, upgrade import and concurrency."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from tests.helpers import ServiceCase, fixture
from tests.test_w2_money import run_threads

STAGE1 = os.path.join(os.path.dirname(__file__), "..", "..", "stage-1")


def iso(delta_seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


class HoldCase(ServiceCase):
    def authorize(self, amount, who="ada", to="bob", key=None, **extra):
        body = {"to_handle": to, "amount": amount, **extra}
        return self.call("POST", "/authorizations", body, token=self.tok[who],
                         key=key or f"a{amount}{to}{sorted(extra.items())}")

    def capture(self, auth_id, body=None, who="bob", key="c"):
        return self.call("POST", f"/authorizations/{auth_id}/capture", body if body is not None
                         else {}, token=self.tok[who], key=key)

    def void(self, auth_id, who="ada"):
        return self.call("POST", f"/authorizations/{auth_id}/void", token=self.tok[who])

    def me(self, who):
        return self.call("GET", "/me", token=self.tok[who])[1]


class AuthorizeTests(HoldCase):
    def test_create_shape_and_hold(self):
        status, a = self.authorize(2000, note="deposit", visibility="private")
        self.assertEqual(status, 201, a)
        self.assertEqual({k: a[k] for k in ("from_user_id", "from_handle", "to_user_id", "to_handle",
                                            "amount", "captured_amount", "remaining_amount",
                                            "payment_ids", "currency", "note", "visibility",
                                            "status", "payment_id")},
                         {"from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob",
                          "to_handle": "bob", "amount": 2000, "captured_amount": 0,
                          "remaining_amount": 2000, "payment_ids": [], "currency": "EUR",
                          "note": "deposit", "visibility": "private", "status": "open",
                          "payment_id": None})
        created = datetime.fromisoformat(a["created_at"])
        self.assertRegex(a["created_at"], r"\.\d{3}\+00:00$")
        self.assertEqual(datetime.fromisoformat(a["expires_at"]) - created, timedelta(seconds=600))
        me = self.me("ada")
        self.assertEqual((me["balance"], me["total"], me["available"], me["held"]),
                         (10000, 10000, 8000, 2000))
        # an open authorization is not a feed item
        self.assertNotIn(a["authorization_id"], json.dumps(self.call(
            "GET", "/activity", token=self.tok["ada"])[1]))

    def test_errors(self):
        self.assertError(self.authorize(10001), 409, "insufficient_funds")
        self.assertError(self.authorize(1, to="ada"), 422, "self_payment")
        self.assertError(self.authorize(1, to="zed"), 404, "not_found")
        self.assertError(self.authorize(0), 422, "validation_failed")
        self.assertError(self.authorize(10 ** 9 + 1), 422, "validation_failed")
        self.assertError(self.authorize(1, visibility="x"), 422, "validation_failed")
        self.assertError(self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1},
                                   token=self.tok["ada"]), 400, "missing_idempotency_key")

    def test_held_funds_cannot_fund_payments_requests_settlements_or_holds(self):
        self.authorize(9000)
        self.assertError(self.call("POST", "/payments", {"to_handle": "bob", "amount": 1001},
                                   token=self.tok["ada"], key="p"), 409, "insufficient_funds")
        self.assertEqual(self.call("POST", "/payments", {"to_handle": "bob", "amount": 1000},
                                   token=self.tok["ada"], key="p2")[0], 201)
        self.assertError(self.authorize(1, key="again"), 409, "insufficient_funds")
        rq = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 1},
                       token=self.tok["bob"], key="r")[1]
        self.assertError(self.call("POST", f"/requests/{rq['request_id']}/pay", {},
                                   token=self.tok["ada"], key="x"), 409, "insufficient_funds")
        self.assertError(self.call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "cy", "amount": 1}]}, token=self.tok["cy"],
            key="s"), 409, "insufficient_funds")
        me = self.me("ada")
        self.assertEqual((me["total"], me["available"], me["held"]), (9000, 0, 9000))

    def test_list_filters(self):
        out = self.authorize(100)[1]
        inc = self.authorize(50, who="bob", to="ada")[1]
        get = lambda **q: [a["authorization_id"] for a in self.call(
            "GET", "/authorizations", token=self.tok["ada"], query=q)[1]["authorizations"]]
        self.assertEqual(get(), [inc["authorization_id"], out["authorization_id"]])
        self.assertEqual(get(direction="outgoing"), [out["authorization_id"]])
        self.assertEqual(get(direction="incoming"), [inc["authorization_id"]])
        self.assertEqual(get(status="captured"), [])
        self.assertEqual(self.call("GET", "/authorizations", token=self.tok["cy"])[1],
                         {"authorizations": [], "has_more": False})
        self.assertError(self.call("GET", "/authorizations", token=self.tok["ada"],
                                   query={"status": "pending"}), 422, "validation_failed")


class CaptureTests(HoldCase):
    def test_default_final_capture_releases_remainder(self):
        a = self.authorize(2000, note="deposit")[1]
        status, payment = self.capture(a["authorization_id"], {"amount": 1500})
        self.assertEqual(status, 201, payment)
        self.assertEqual((payment["amount"], payment["authorization_id"], payment["request_id"],
                          payment["note"], payment["from_handle"], payment["to_handle"]),
                         (1500, a["authorization_id"], None, "deposit", "ada", "bob"))
        me = self.me("ada")
        self.assertEqual((me["total"], me["available"], me["held"]), (8500, 8500, 0))
        self.assertEqual(self.me("bob")["total"], 4000)
        listed = self.call("GET", "/authorizations", token=self.tok["bob"])[1]["authorizations"][0]
        self.assertEqual((listed["status"], listed["captured_amount"], listed["remaining_amount"],
                          listed["payment_id"], listed["payment_ids"]),
                         ("captured", 1500, 0, payment["payment_id"], [payment["payment_id"]]))
        self.assertEqual(self.capture(a["authorization_id"], {"amount": 1500}), (200, payment))
        self.assertError(self.capture(a["authorization_id"], {"amount": 1}, key="c2"),
                         409, "authorization_not_open")
        feed = self.call("GET", "/activity", token=self.tok["cy"])[1]["payments"]
        self.assertEqual(feed[0]["payment_id"], payment["payment_id"])

    def test_extended_partial_captures(self):
        a = self.authorize(2000)[1]
        aid = a["authorization_id"]
        first = self.capture(aid, {"amount": 700, "final": False}, key="c1")[1]
        self.assertEqual(self.me("ada")["held"], 1300)
        self.assertError(self.capture(aid, {"amount": 1301, "final": False}, key="c2"),
                         422, "capture_exceeds_authorization")
        second = self.capture(aid, {"final": False}, key="c3")[1]  # defaults to remainder
        self.assertEqual(second["amount"], 1300)
        record = self.call("GET", "/authorizations", token=self.tok["ada"])[1]["authorizations"][0]
        self.assertEqual((record["status"], record["captured_amount"], record["remaining_amount"],
                          record["payment_ids"], record["payment_id"]),
                         ("captured", 2000, 0, [first["payment_id"], second["payment_id"]],
                          second["payment_id"]))
        self.assertEqual(self.me("ada")["total"], 8000)

    def test_capture_rules_and_order(self):
        aid = self.authorize(2000)[1]["authorization_id"]
        self.assertError(self.capture(aid, {"amount": 0}), 422, "validation_failed")
        self.assertError(self.capture(aid, {"amount": None}), 422, "validation_failed")
        self.assertError(self.capture(aid, {"amount": 1.5}), 422, "validation_failed")
        self.assertError(self.capture(aid, {"final": "false"}), 400, "malformed_request")
        self.assertError(self.capture(aid, {"amount": 10 ** 10}), 422,
                         "capture_exceeds_authorization")
        self.assertError(self.capture(aid, who="ada"), 403, "forbidden")
        self.assertError(self.capture(aid, who="cy"), 403, "forbidden")
        self.assertError(self.capture("a_nope"), 404, "not_found")
        self.assertEqual(self.capture(aid, {}, key="k")[0], 201)
        self.assertError(self.capture(aid, {"amount": 2000}, key="k"), 409, "idempotency_key_reuse")

    def test_new_body_field_is_not_a_replay(self):
        aid = self.authorize(2000)[1]["authorization_id"]
        self.assertEqual(self.capture(aid, {"amount": 700}, key="k")[0], 201)
        self.assertError(self.capture(aid, {"amount": 700, "final": True}, key="k"),
                         409, "idempotency_key_reuse")


class VoidTests(HoldCase):
    def test_void_rules(self):
        aid = self.authorize(2000)[1]["authorization_id"]
        self.assertError(self.void(aid, who="bob"), 403, "forbidden")
        self.assertError(self.void(aid, who="cy"), 403, "forbidden")
        self.assertError(self.void("a_nope"), 404, "not_found")
        status, body = self.void(aid)
        self.assertEqual((status, body["status"], body["remaining_amount"]), (200, "voided", 0))
        self.assertEqual(self.me("ada")["available"], 10000)
        self.assertEqual(self.void(aid)[0], 200)
        self.assertError(self.capture(aid), 409, "authorization_not_open")
        captured = self.authorize(10, key="x")[1]["authorization_id"]
        self.capture(captured, key="cx")
        self.assertError(self.void(captured), 409, "authorization_not_open")

    def test_void_after_partial_capture_keeps_capture_records(self):
        aid = self.authorize(2000)[1]["authorization_id"]
        payment = self.capture(aid, {"amount": 500, "final": False})[1]
        body = self.void(aid)[1]
        self.assertEqual((body["status"], body["captured_amount"], body["payment_ids"],
                          body["remaining_amount"]), ("voided", 500, [payment["payment_id"]], 0))
        me = self.me("ada")
        self.assertEqual((me["total"], me["available"], me["held"]), (9500, 9500, 0))


class ExpiryTests(HoldCase):
    def reset_with(self, **extra):
        f = fixture()
        f.update(extra)
        status, body = self.call("POST", "/_test/reset", f)
        self.assertEqual(status, 204, body)
        self.tok = {h: self.login(f"{h}@example.com") for h in ("ada", "bob", "cy")}

    def test_ttl_one_second_expires_without_writes(self):
        self.reset_with(authorization_ttl_seconds=1)
        quick = self.authorize(100, key="q")[1]
        self.assertEqual(self.capture(quick["authorization_id"], key="q")[0], 201)
        slow = self.authorize(300, key="s")[1]
        self.assertEqual(self.me("ada")["held"], 300)
        time.sleep(1.2)
        me = self.me("ada")
        self.assertEqual((me["held"], me["available"]), (0, me["total"]))
        listed = {a["authorization_id"]: a["status"] for a in self.call(
            "GET", "/authorizations", token=self.tok["ada"])[1]["authorizations"]}
        self.assertEqual(listed[slow["authorization_id"]], "expired")
        self.assertEqual(self.call("GET", "/authorizations", token=self.tok["ada"],
                                   query={"status": "open"})[1]["authorizations"], [])
        self.assertError(self.capture(slow["authorization_id"], key="late"),
                         409, "authorization_expired")
        self.assertError(self.void(slow["authorization_id"]), 409, "authorization_not_open")

    def test_seeded_authorizations(self):
        self.reset_with(authorizations=[
            {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000,
             "note": "deposit", "visibility": "public", "status": "open",
             "expires_at": iso(3600)},
            {"id": "a_past", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 9999,
             "status": "open", "expires_at": iso(-3600)},
            {"id": "a_done", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 5,
             "status": "captured", "expires_at": iso(3600)},
        ])
        me = self.me("ada")
        self.assertEqual((me["total"], me["available"], me["held"]), (10000, 8000, 2000))
        listed = {a["authorization_id"]: a for a in self.call(
            "GET", "/authorizations", token=self.tok["ada"])[1]["authorizations"]}
        self.assertEqual(listed["a_past"]["status"], "expired")
        self.assertEqual((listed["a_done"]["captured_amount"], listed["a_done"]["payment_ids"]),
                         (0, []))
        self.assertEqual(self.capture("a_open", {"amount": 500})[0], 201)

    def test_seeded_hold_over_balance_and_bad_entries_are_422(self):
        good = {"id": "a1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 2500,
                "status": "open", "expires_at": iso(3600)}
        bad_cases = [
            {**good, "amount": 2501},
            {**good, "to_user_id": "u_bob"},
            {**good, "from_user_id": "u_nobody"},
            {**good, "amount": 0},
            {**good, "amount": 1.5},
            {**good, "visibility": "x"},
            {**good, "status": "pending"},
            {**good, "expires_at": "tomorrow"},
            {**good, "expires_at": "2026-09-24T13:20:00"},
        ]
        for bad in bad_cases:
            f = fixture()
            f["authorizations"] = [bad]
            self.assertError(self.call("POST", "/_test/reset", f), 422, "validation_failed")
        for ttl in (0, -1, 1.5, "600", True):
            f = fixture()
            f["authorization_ttl_seconds"] = ttl
            self.assertError(self.call("POST", "/_test/reset", f), 422, "validation_failed")
        f = fixture()
        f["authorizations"] = [good, dict(good, amount=1)]
        self.assertError(self.call("POST", "/_test/reset", f), 422, "validation_failed")
        self.assertEqual(self.me("ada")["total"], 10000)  # state untouched
        f["authorizations"] = [good]
        self.assertEqual(self.call("POST", "/_test/reset", f)[0], 204)


class UpgradeTests(HoldCase):
    def test_stage2_round_trip_with_authorizations(self):
        aid = self.authorize(2000)[1]["authorization_id"]
        payment = self.capture(aid, {"amount": 500, "final": False}, key="k")[1]
        doc = json.loads(json.dumps(self.call("GET", "/_test/export")[1]))
        self.assertEqual(doc["state"]["authorization_ttl_seconds"], 600)
        self.call("POST", "/_test/reset", fixture())
        self.assertEqual(self.call("POST", "/_test/import", doc)[0], 204)
        self.assertEqual(json.loads(json.dumps(self.call("GET", "/_test/export")[1])), doc)
        self.tok = {h: self.login(f"{h}@example.com") for h in ("ada", "bob", "cy")}
        self.assertEqual(self.me("ada")["held"], 1500)
        self.assertEqual(self.capture(aid, {"amount": 500, "final": False}, key="k"),
                         (200, payment))

    def test_stage1_export_imports(self):
        """Generate a real export with the stage-1 code, then import it here (R-231)."""
        script = r'''
import json, sys
from pocketful.app import Request, dispatch
from pocketful.state import Store
fixture = json.loads(sys.stdin.read())
st = Store()
call = lambda m, p, b=None, h=None: dispatch(st, Request(m, p, {}, h or {},
                                                         json.dumps(b).encode() if b else b""))
call("POST", "/_test/reset", fixture)
tok = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[1]["token"]
auth = {"Authorization": "Bearer " + tok, "Idempotency-Key": "lost"}
pay = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, auth)[1]
print(json.dumps({"token": tok, "payment": pay, "export": call("GET", "/_test/export")[1]}))
'''
        out = subprocess.run([sys.executable, "-c", script], cwd=STAGE1, input=json.dumps(fixture()),
                             capture_output=True, text=True, timeout=60, check=True)
        data = json.loads(out.stdout)
        self.assertNotIn("authorizations", data["export"]["state"])
        self.assertEqual(self.call("POST", "/_test/import", data["export"])[0], 204)
        token = data["token"]
        status, me = self.call("GET", "/me", token=token)
        self.assertEqual((status, me["total"], me["available"], me["held"]), (200, 9900, 9900, 0))
        self.assertEqual(self.call("POST", "/payments", {"to_handle": "bob", "amount": 100},
                                   token=token, key="lost"), (200, data["payment"]))
        feed = self.call("GET", "/activity", token=token)[1]["payments"]
        self.assertTrue(all(p["authorization_id"] is None for p in feed))
        self.assertEqual(self.login("bob@example.com") is not None, True)
        status, rq_list = self.call("GET", "/requests", token=token)
        rid = rq_list["requests"][0]["request_id"]
        self.assertEqual(self.call("POST", f"/requests/{rid}/pay", {}, token=token, key="p")[0], 201)
        self.assertEqual(self.authorize(10, key="new")[0] if False else
                         self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 10},
                                   token=token, key="new")[0], 201)


class HoldConcurrencyTests(HoldCase):
    def test_storm_against_one_wallet_keeps_invariants(self):
        """I-200/I-201: payments, holds and settlements racing on bob's 2500."""
        def act(i):
            kind = i % 3
            if kind == 0:
                return self.call("POST", "/payments", {"to_handle": "cy", "amount": 100},
                                 token=self.tok["bob"], key=f"p{i}")
            if kind == 1:
                return self.authorize(100, who="bob", to="cy", key=f"a{i}")
            return self.call("POST", "/settlements", {"transfers": [
                {"from_handle": "bob", "to_handle": "ada", "amount": 100}]},
                token=self.tok["cy"], key=f"s{i}")

        results = run_threads(60, act)
        self.assertTrue(all(s in (201, 409) for s, _ in results), results)
        self.assertEqual(sum(1 for s, _ in results if s == 201), 25)
        me = self.me("bob")
        self.assertEqual((me["available"], me["total"] - me["held"]), (0, 0))
        self.assertEqual(sum(self.me(u)["total"] for u in ("ada", "bob", "cy")), 12500)

    def test_concurrent_captures_never_over_capture(self):
        aid = self.authorize(1000)[1]["authorization_id"]
        results = run_threads(30, lambda i: self.capture(aid, {"amount": 100, "final": False},
                                                         key=f"k{i}"))
        ok = [r for r in results if r[0] == 201]
        self.assertEqual(len(ok), 10)
        self.assertTrue(all(r[0] in (201, 409) for r in results))
        self.assertEqual(self.me("bob")["total"], 3500)
        self.assertEqual(self.me("ada")["held"], 0)

    def test_concurrent_identical_captures_one_payment(self):
        aid = self.authorize(1000)[1]["authorization_id"]
        results = run_threads(30, lambda i: self.capture(aid, {"amount": 400}, key="same"))
        self.assertEqual(sorted(r[0] for r in results), [200] * 29 + [201])
        self.assertEqual(len({r[1]["payment_id"] for r in results}), 1)
        self.assertEqual(self.me("ada")["total"], 9600)

    def test_capture_vs_void_serial_outcome(self):
        for round_ in range(10):
            aid = self.authorize(100, key=f"r{round_}")[1]["authorization_id"]
            actions = [lambda: self.capture(aid, {"amount": 60}, key=f"c{round_}"),
                       lambda: self.void(aid)]
            cap, vd = run_threads(2, lambda i: actions[i]())
            if cap[0] == 201:
                self.assertError(vd, 409, "authorization_not_open")
            else:
                self.assertEqual((vd[0], cap[1]["error"]["code"]), (200, "authorization_not_open"))
        me = self.me("ada")
        self.assertEqual((me["held"], me["available"]), (0, me["total"]))
