"""W3: splits, settlements, export/import round trips, and their concurrency."""
import json

from pocketful.splits import equal_shares
from tests.helpers import ServiceCase
from tests.test_w2_money import run_threads


class ShareTests(ServiceCase):
    def test_share_table(self):
        table = [(1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                 (999, 3, [333, 333, 333]), (5, 5, [1, 1, 1, 1, 1])]
        for amount, n, shares in table:
            self.assertEqual(equal_shares(amount, n), shares)
        for amount in range(1, 200):
            for n in range(1, 8):
                shares = equal_shares(amount, n)
                self.assertEqual(sum(shares), amount)
                self.assertLessEqual(max(shares) - min(shares), 1)


class SplitTests(ServiceCase):
    def split(self, body, who="ada", key="s"):
        return self.call("POST", "/splits", body, token=self.tok[who], key=key)

    def test_split_creates_requests_except_caller(self):
        status, body = self.split({"amount": 1000, "participant_handles": ["bob", "ada", "cy"],
                                   "note": "dinner"})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["shares"], [{"handle": "bob", "amount": 334},
                                          {"handle": "ada", "amount": 333},
                                          {"handle": "cy", "amount": 333}])
        self.assertEqual([(r["payer_handle"], r["amount"], r["requester_id"], r["status"])
                          for r in body["requests"]],
                         [("bob", 334, "u_ada", "pending"), ("cy", 333, "u_ada", "pending")])
        self.assertEqual((body["currency"], body["note"], body["amount"]), ("EUR", "dinner", 1000))
        incoming = self.call("GET", "/requests", token=self.tok["cy"],
                             query={"direction": "incoming"})[1]["requests"]
        self.assertEqual(incoming[0]["request_id"], body["requests"][1]["request_id"])
        self.assertEqual(self.balance("ada"), 10000)  # no balance checked or moved

    def test_zero_share_and_caller_only(self):
        status, body = self.split({"amount": 1, "participant_handles": ["ada", "bob", "cy"]})
        self.assertEqual([r["amount"] for r in body["requests"]], [0, 0])
        status, body = self.split({"amount": 5, "participant_handles": ["ada"]}, key="t")
        self.assertEqual((status, body["requests"], body["shares"]),
                         (201, [], [{"handle": "ada", "amount": 5}]))

    def test_split_errors(self):
        self.assertError(self.split({"amount": 10, "participant_handles": []}), 422,
                         "validation_failed")
        self.assertError(self.split({"amount": 10, "participant_handles": ["bob", "bob"]}), 422,
                         "validation_failed")
        self.assertError(self.split({"amount": 0, "participant_handles": ["bob"]}), 422,
                         "validation_failed")
        self.assertError(self.split({"amount": 10, "participant_handles": "bob"}), 400,
                         "malformed_request")
        self.assertError(self.split({"amount": 10, "participant_handles": ["bob", 3]}), 400,
                         "malformed_request")
        many = [f"ghost{i}" for i in range(1000)]
        self.assertError(self.split({"amount": 10, "participant_handles": many}), 404, "not_found")
        self.assertEqual(self.call("GET", "/requests", token=self.tok["ada"],
                                   query={"direction": "outgoing"})[1]["requests"], [])

    def test_concurrent_identical_splits_one_effect(self):
        body = {"amount": 30, "participant_handles": ["bob", "cy"]}
        results = run_threads(30, lambda i: self.split(body))
        self.assertEqual(sorted(r[0] for r in results), [200] * 29 + [201])
        self.assertEqual(len({r[1]["split_id"] for r in results}), 1)
        outgoing = self.call("GET", "/requests", token=self.tok["ada"],
                             query={"direction": "outgoing"})[1]["requests"]
        self.assertEqual(len(outgoing), 2)


class SettlementTests(ServiceCase):
    def settle(self, transfers, who="cy", key="st"):
        return self.call("POST", "/settlements", {"transfers": transfers},
                         token=self.tok[who], key=key)

    def test_net_affordability_and_shape(self):
        # cy has 0: cy->ada 100 is only affordable because bob->cy 100 lands in the same batch.
        status, body = self.settle([{"from_handle": "bob", "to_handle": "cy", "amount": 100},
                                    {"from_handle": "cy", "to_handle": "ada", "amount": 100,
                                     "visibility": "private", "note": "net"}])
        self.assertEqual(status, 201, body)
        self.assertEqual([p["settlement_id"] for p in body["payments"]],
                         [body["settlement_id"]] * 2)
        self.assertTrue(all(p["created_at"] == body["committed_at"] and p["request_id"] is None
                            for p in body["payments"]))
        self.assertEqual([(p["from_handle"], p["visibility"]) for p in body["payments"]],
                         [("bob", "public"), ("cy", "private")])
        self.assertEqual([self.balance(u) for u in ("ada", "bob", "cy")], [10100, 2400, 0])
        bob_feed = self.call("GET", "/activity", token=self.tok["bob"])[1]["payments"]
        self.assertNotIn(body["payments"][1]["payment_id"], [p["payment_id"] for p in bob_feed])
        self.assertEqual(self.settle([{"from_handle": "bob", "to_handle": "cy", "amount": 100},
                                      {"from_handle": "cy", "to_handle": "ada", "amount": 100,
                                       "visibility": "private", "note": "net"}]), (200, body))

    def test_all_or_nothing(self):
        self.assertError(self.settle([{"from_handle": "ada", "to_handle": "cy", "amount": 100},
                                      {"from_handle": "bob", "to_handle": "cy", "amount": 2501}]),
                         409, "insufficient_funds")
        self.assertEqual([self.balance(u) for u in ("ada", "bob", "cy")], [10000, 2500, 0])
        # the failed key was not claimed
        self.assertEqual(self.settle([{"from_handle": "ada", "to_handle": "cy", "amount": 1}])[0], 201)

    def test_errors_and_precedence(self):
        self.assertError(self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 1}],
                                     who="ada"), 403, "forbidden")
        self.assertError(self.call("POST", "/settlements", {"transfers": []}), 401, "unauthenticated")
        for bad in ({}, {"transfers": {}}, {"transfers": []}, {"transfers": [1]},
                    {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}] * 33}):
            self.assertError(self.call("POST", "/settlements", bad, token=self.tok["cy"], key="x"),
                             422, "validation_failed")
        self.assertError(self.settle([{"from_handle": 1, "to_handle": "bob", "amount": 1}]),
                         400, "malformed_request")
        self.assertError(self.settle([{"from_handle": "ada", "to_handle": "ada", "amount": 1}]),
                         422, "self_payment")
        # first failing entry in input order wins, before insufficient funds
        self.assertError(self.settle([{"from_handle": "bob", "to_handle": "ada", "amount": 10 ** 9},
                                      {"from_handle": "zed", "to_handle": "ada", "amount": 1},
                                      {"from_handle": "ada", "to_handle": "ada", "amount": 1}]),
                         404, "not_found")
        self.assertError(self.settle([{"from_handle": "ada", "to_handle": "ada", "amount": 1},
                                      {"from_handle": "zed", "to_handle": "ada", "amount": 1}]),
                         422, "self_payment")
        self.assertEqual([self.balance(u) for u in ("ada", "bob", "cy")], [10000, 2500, 0])

    def test_operator_gets_no_extra_visibility(self):
        self.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "visibility": "private"},
                  token=self.tok["ada"], key="p")
        feed = self.call("GET", "/activity", token=self.tok["cy"])[1]["payments"]
        self.assertEqual([p["payment_id"] for p in feed], ["p_1"])
        self.assertEqual(self.call("GET", "/requests", token=self.tok["cy"])[1]["requests"], [])

    def test_concurrent_identical_settlements_one_effect(self):
        transfers = [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]
        results = run_threads(30, lambda i: self.settle(transfers))
        self.assertEqual(sorted(r[0] for r in results), [200] * 29 + [201])
        self.assertEqual(self.balance("ada"), 9900)

    def test_concurrent_settlements_never_overdraw(self):
        results = run_threads(40, lambda i: self.settle(
            [{"from_handle": "bob", "to_handle": "ada", "amount": 100}], key=f"k{i}"))
        self.assertEqual(sum(1 for s, _ in results if s == 201), 25)
        self.assertEqual(self.balance("bob"), 0)


class ExportImportTests(ServiceCase):
    def export(self):
        status, body = self.call("GET", "/_test/export")
        self.assertEqual(status, 200)
        return json.loads(json.dumps(body))  # through the wire format

    def import_(self, doc):
        return self.call("POST", "/_test/import", doc)

    def test_round_trip_keeps_tokens_receipts_and_ids(self):
        payment = self.call("POST", "/payments", {"to_handle": "bob", "amount": 100},
                            token=self.tok["ada"], key="k")[1]
        rq = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 5},
                       token=self.tok["bob"], key="r")[1]
        self.call("POST", "/requests/" + rq["request_id"] + "/cancel", token=self.tok["bob"])
        split = self.call("POST", "/splits", {"amount": 3, "participant_handles": ["bob"]},
                          token=self.tok["ada"], key="s")[1]
        settlement = self.call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "cy", "amount": 7}]}, token=self.tok["cy"],
            key="st")[1]
        self.call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9},
                  token=self.tok["ada"], key="failed")
        doc = self.export()
        self.assertEqual((doc["track"], doc["format_version"]), ("pocketful", 1))
        self.assertNotIn("correct horse", json.dumps(doc))

        self.call("POST", "/_test/reset", {"currency": "JPY", "minor_units": 0, "users": []})
        self.assertEqual(self.import_(doc), (204, None))
        self.assertEqual(self.import_(doc), (204, None))  # repeatable, no duplication
        self.assertEqual(self.export(), doc)

        self.assertEqual(self.balance("ada"), 10000 - 100 - 7)
        self.assertEqual(self.login("ada@example.com") is not None, True)
        self.assertEqual(self.call("POST", "/payments", {"to_handle": "bob", "amount": 100},
                                   token=self.tok["ada"], key="k"), (200, payment))
        self.assertEqual(self.call("POST", "/splits", {"amount": 3, "participant_handles": ["bob"]},
                                   token=self.tok["ada"], key="s"), (200, split))
        self.assertEqual(self.call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "cy", "amount": 7}]}, token=self.tok["cy"],
            key="st"), (200, settlement))
        self.assertEqual(self.call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                                   token=self.tok["ada"], key="failed")[0], 201)
        new = self.call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                        token=self.tok["ada"], key="new")[1]
        self.assertNotIn(new["payment_id"], [p["payment_id"] for p in doc["state"]["payments"]])
        self.assertEqual(sum(self.balance(u) for u in ("ada", "bob", "cy")), 12500)

    def test_export_is_a_snapshot(self):
        doc = self.export()
        self.call("POST", "/payments", {"to_handle": "bob", "amount": 100},
                  token=self.tok["ada"], key="k")
        self.assertEqual(self.import_(doc)[0], 204)
        self.assertEqual(self.balance("ada"), 10000)

    def test_invalid_imports_change_nothing(self):
        doc = self.export()
        self.call("POST", "/payments", {"to_handle": "bob", "amount": 100},
                  token=self.tok["ada"], key="k")
        bad_docs = [{}, {"track": "other", "format_version": 1, "state": doc["state"]},
                    {"track": "pocketful", "format_version": 2, "state": doc["state"]},
                    {"track": "pocketful", "format_version": True, "state": doc["state"]},
                    {"track": "pocketful", "format_version": 1}]
        for mutate in (lambda s: s.pop("users"),
                       lambda s: s["users"][0].update(balance=-1),
                       lambda s: s["users"][0].update(pw_hash="plain"),
                       lambda s: s["tokens"].update(x=["u_ada"]),
                       lambda s: s["payments"][0].update(amount=1.5),
                       lambda s: s["requests"][0].update(status="odd"),
                       lambda s: s["operators"].append({}),
                       lambda s: s["idempotency"].append({"user_id": "nobody"})):
            broken = json.loads(json.dumps(doc))
            mutate(broken["state"])
            bad_docs.append(broken)
        for bad in bad_docs:
            self.assertError(self.import_(bad), 422, "validation_failed")
        self.assertError(self.call("POST", "/_test/import", raw=b"{nope"), 400, "malformed_request")
        self.assertEqual(self.balance("ada"), 9900)  # destination intact, tokens still valid
