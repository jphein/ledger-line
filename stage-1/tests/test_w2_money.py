"""W2: idempotency, payments, requests, activity, and concurrency invariants."""
import threading

from tests.helpers import ServiceCase


def run_threads(count, target):
    results = [None] * count
    barrier = threading.Barrier(count)

    def worker(i):
        barrier.wait()
        results[i] = target(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


class PaymentTests(ServiceCase):
    def pay(self, body, who="ada", key="k1"):
        return self.call("POST", "/payments", body, token=self.tok[who], key=key)

    def test_payment_moves_money_and_has_full_body(self):
        status, body = self.pay({"to_handle": "bob", "amount": 1500, "note": "dinner"})
        self.assertEqual(status, 201, body)
        self.assertEqual({k: body[k] for k in ("from_user_id", "from_handle", "to_user_id",
                                                "to_handle", "amount", "currency", "note",
                                                "visibility", "request_id", "settlement_id")},
                         {"from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob",
                          "to_handle": "bob", "amount": 1500, "currency": "EUR",
                          "note": "dinner", "visibility": "public", "request_id": None,
                          "settlement_id": None})
        self.assertRegex(body["created_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual((self.balance("ada"), self.balance("bob")), (8500, 4000))

    def test_amount_forms(self):
        for i, amount in enumerate((1000, 1000.0, 1e3)):
            status, body = self.pay({"to_handle": "bob", "amount": amount}, key=f"a{i}")
            self.assertEqual((status, body["amount"]), (201, 1000))
            self.assertIs(type(body["amount"]), int)
        for i, amount in enumerate((0, -1, 1000000001, 10.5, "100", True, None)):
            self.assertError(self.pay({"to_handle": "bob", "amount": amount}, key=f"b{i}"),
                             422, "validation_failed")
        self.assertError(self.call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e400}',
                                   token=self.tok["ada"], key="inf"), 422, "validation_failed")

    def test_payment_errors(self):
        self.assertError(self.pay({"to_handle": "bob", "amount": 10001}), 409, "insufficient_funds")
        self.assertError(self.pay({"to_handle": "ada", "amount": 1}), 422, "self_payment")
        self.assertError(self.pay({"to_handle": "zed", "amount": 1}), 404, "not_found")
        self.assertError(self.pay({"to_handle": 5, "amount": 1}), 400, "malformed_request")
        self.assertError(self.pay({"amount": 1}), 422, "validation_failed")
        self.assertError(self.pay({"to_handle": "bob", "amount": 1, "note": None}),
                         422, "validation_failed")
        self.assertError(self.pay({"to_handle": "bob", "amount": 1, "visibility": None}),
                         422, "validation_failed")
        self.assertError(self.pay({"to_handle": "bob", "amount": 1, "visibility": "friends"}),
                         422, "validation_failed")
        self.assertError(self.pay({"to_handle": "bob", "amount": 1, "note": "x" * 201}),
                         422, "validation_failed")
        self.assertEqual(self.balance("ada"), 10000)  # failures leave no trace

    def test_note_verbatim_and_length_in_code_points(self):
        note = "  ünï 😀 <b>&amp;</b>  " + "😀" * 178
        self.assertEqual(len(note), 200)
        status, body = self.pay({"to_handle": "bob", "amount": 1, "note": note})
        self.assertEqual((status, body["note"]), (201, note))
        self.assertError(self.pay({"to_handle": "bob", "amount": 1, "note": note + "😀"}, key="k2"),
                         422, "validation_failed")

    def test_key_header_rules(self):
        self.assertError(self.pay({"to_handle": "bob", "amount": 1}, key=None),
                         400, "missing_idempotency_key")
        self.assertError(self.pay({"to_handle": "bob", "amount": 1}, key=""),
                         400, "missing_idempotency_key")
        self.assertError(self.pay({"to_handle": "bob", "amount": 1}, key="k" * 256),
                         422, "validation_failed")
        self.assertEqual(self.pay({"to_handle": "bob", "amount": 1}, key="k" * 255)[0], 201)

    def test_check_order_auth_then_body_then_key(self):
        self.assertError(self.call("POST", "/payments", raw=b"{", key=None), 401, "unauthenticated")
        self.assertError(self.call("POST", "/payments", raw=b"{", token=self.tok["ada"], key=None),
                         400, "malformed_request")
        self.assertError(self.call("POST", "/payments", raw=b"[1]", token=self.tok["ada"],
                                   key="k"), 400, "malformed_request")


class IdempotencyTests(ServiceCase):
    def test_replay_reuse_and_scope(self):
        body = {"to_handle": "bob", "amount": 100}
        first = self.call("POST", "/payments", body, token=self.tok["ada"], key="k")
        self.assertEqual(first[0], 201)
        replay = self.call("POST", "/payments", raw=b'{ "amount": 1e2, "to_handle": "bob" }',
                           token=self.tok["ada"], key="k")
        self.assertEqual(replay, (200, first[1]))
        self.assertError(self.call("POST", "/payments", {"to_handle": "bob", "amount": 101},
                                   token=self.tok["ada"], key="k"), 409, "idempotency_key_reuse")
        # Claimed key resolves before field validation (R-51).
        self.assertError(self.call("POST", "/payments", {"to_handle": "bob", "amount": "bad"},
                                   token=self.tok["ada"], key="k"), 409, "idempotency_key_reuse")
        # Another user, same key: independent (R-42).
        self.assertEqual(self.call("POST", "/payments", {"to_handle": "ada", "amount": 100},
                                   token=self.tok["bob"], key="k")[0], 201)
        # Same key on a different path is a new request (R-43, S-07).
        self.assertEqual(self.call("POST", "/requests", {"payer_handle": "bob", "amount": 100},
                                   token=self.tok["ada"], key="k")[0], 201)
        self.assertEqual(self.balance("ada"), 10000 - 100 + 100)

    def test_bool_body_is_not_a_replay(self):
        self.assertEqual(self.call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                                   token=self.tok["ada"], key="k")[0], 201)
        self.assertError(self.call("POST", "/payments", {"to_handle": "bob", "amount": True},
                                   token=self.tok["ada"], key="k"), 409, "idempotency_key_reuse")

    def test_failed_key_is_reusable(self):
        self.assertError(self.call("POST", "/payments", {"to_handle": "bob", "amount": 99999},
                                   token=self.tok["ada"], key="k"), 409, "insufficient_funds")
        self.assertEqual(self.call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                                   token=self.tok["ada"], key="k")[0], 201)

    def test_concurrent_identical_requests_one_effect(self):
        results = run_threads(50, lambda i: self.call(
            "POST", "/payments", {"to_handle": "bob", "amount": 100},
            token=self.tok["ada"], key="same"))
        statuses = sorted(r[0] for r in results)
        self.assertEqual(statuses, [200] * 49 + [201])
        self.assertEqual(len({r[1]["payment_id"] for r in results}), 1)
        self.assertEqual(self.balance("ada"), 9900)


class RequestTests(ServiceCase):
    def request_money(self, payer="ada", amount=1200, who="bob", key="r"):
        status, body = self.call("POST", "/requests", {"payer_handle": payer, "amount": amount,
                                                       "note": "taxi"}, token=self.tok[who], key=key)
        self.assertEqual(status, 201, body)
        return body

    def test_create_shape_and_errors(self):
        body = self.request_money(amount=10 ** 9)  # above the payer's balance: allowed (R-65)
        self.assertEqual({k: body[k] for k in ("requester_id", "requester_handle", "payer_id",
                                                "payer_handle", "status", "payment_id")},
                         {"requester_id": "u_bob", "requester_handle": "bob", "payer_id": "u_ada",
                          "payer_handle": "ada", "status": "pending", "payment_id": None})
        call = lambda b, k: self.call("POST", "/requests", b, token=self.tok["bob"], key=k)
        self.assertError(call({"payer_handle": "bob", "amount": 1}, "1"), 422, "self_request")
        self.assertError(call({"payer_handle": "zed", "amount": 1}, "2"), 404, "not_found")
        self.assertError(call({"payer_handle": "ada", "amount": 0}, "3"), 422, "validation_failed")

    def test_pay_flow_and_replay_after_paid(self):
        rq = self.request_money()
        pay = lambda body, key="p", who="ada": self.call(
            "POST", f"/requests/{rq['request_id']}/pay", body, token=self.tok[who], key=key)
        self.assertError(pay({}, who="bob"), 403, "forbidden")
        self.assertError(pay({}, who="cy"), 403, "forbidden")
        self.assertError(pay({"visibility": "x"}), 422, "validation_failed")
        status, payment = pay({"visibility": "private"})
        self.assertEqual(status, 201)
        self.assertEqual((payment["request_id"], payment["visibility"], payment["amount"]),
                         (rq["request_id"], "private", 1200))
        self.assertEqual(pay({"visibility": "private"}), (200, payment))
        self.assertError(pay({}, key="other"), 409, "request_not_pending")
        self.assertError(pay({}), 409, "idempotency_key_reuse")
        self.assertEqual((self.balance("ada"), self.balance("bob")), (8800, 3700))
        listed = self.call("GET", "/requests", token=self.tok["bob"])[1]["requests"]
        mine = [r for r in listed if r["request_id"] == rq["request_id"]][0]
        self.assertEqual((mine["status"], mine["payment_id"]), ("paid", payment["payment_id"]))

    def test_empty_body_equals_empty_object_but_not_public(self):
        rq = self.request_money(amount=1)
        path = f"/requests/{rq['request_id']}/pay"
        first = self.call("POST", path, raw=b"", token=self.tok["ada"], key="p")
        self.assertEqual(first[0], 201)
        self.assertEqual(self.call("POST", path, {}, token=self.tok["ada"], key="p"), (200, first[1]))
        self.assertError(self.call("POST", path, {"visibility": "public"}, token=self.tok["ada"],
                                   key="p"), 409, "idempotency_key_reuse")

    def test_insufficient_then_payable_later(self):
        rq = self.request_money(payer="cy", amount=500)
        path = f"/requests/{rq['request_id']}/pay"
        self.assertError(self.call("POST", path, {}, token=self.tok["cy"], key="p"),
                         409, "insufficient_funds")
        self.call("POST", "/payments", {"to_handle": "cy", "amount": 500}, token=self.tok["ada"],
                  key="fund")
        self.assertEqual(self.call("POST", path, {}, token=self.tok["cy"], key="p")[0], 201)
        self.assertEqual(self.balance("cy"), 0)

    def test_decline_and_cancel(self):
        rq = self.request_money()
        rid = rq["request_id"]
        self.assertError(self.call("POST", f"/requests/{rid}/decline", token=self.tok["bob"]),
                         403, "forbidden")
        self.assertError(self.call("POST", f"/requests/{rid}/cancel", token=self.tok["ada"]),
                         403, "forbidden")
        self.assertError(self.call("POST", "/requests/nope/decline", token=self.tok["ada"]),
                         404, "not_found")
        status, body = self.call("POST", f"/requests/{rid}/decline", raw=b"garbage",
                                 token=self.tok["ada"])
        self.assertEqual((status, body["status"]), (200, "declined"))
        self.assertEqual(self.call("POST", f"/requests/{rid}/decline", token=self.tok["ada"])[0], 200)
        self.assertError(self.call("POST", f"/requests/{rid}/cancel", token=self.tok["bob"]),
                         409, "request_not_pending")
        self.assertError(self.call("POST", f"/requests/{rid}/pay", {}, token=self.tok["ada"], key="x"),
                         409, "request_not_pending")
        other = self.request_money(key="r2")
        oid = other["request_id"]
        self.assertEqual(self.call("POST", f"/requests/{oid}/cancel", token=self.tok["bob"])[1]["status"],
                         "cancelled")
        self.assertEqual(self.call("POST", f"/requests/{oid}/cancel", token=self.tok["bob"])[0], 200)
        self.assertError(self.call("POST", f"/requests/{oid}/decline", token=self.tok["ada"]),
                         409, "request_not_pending")

    def test_list_filters_and_paging(self):
        for i in range(3):
            self.request_money(key=f"r{i}")
        get = lambda **q: self.call("GET", "/requests", token=self.tok["ada"], query=q)
        status, body = get(direction="incoming")
        self.assertEqual(len(body["requests"]), 4)  # 3 new + seeded rq_1
        self.assertEqual(body["requests"][-1]["request_id"], "rq_1")  # newest first
        self.assertEqual(len(get(direction="outgoing")[1]["requests"]), 0)
        self.assertEqual(get(limit="2")[1]["has_more"], True)
        self.assertEqual(get(limit="2", offset="2")[1]["has_more"], False)  # exact boundary
        self.assertEqual(get(limit="4")[1]["has_more"], False)
        for bad in ({"limit": "0"}, {"limit": "201"}, {"limit": "4.0"}, {"limit": "+4"},
                    {"limit": "1e9"}, {"offset": "-1"}, {"direction": "sideways"},
                    {"status": "open"}):
            self.assertError(get(**bad), 422, "validation_failed")
        self.assertEqual(self.call("GET", "/requests", token=self.tok["cy"])[1]["requests"], [])


class ActivityTests(ServiceCase):
    def test_feed_contract(self):
        pay = lambda who, to, vis, key: self.call(
            "POST", "/payments", {"to_handle": to, "amount": 1, "visibility": vis},
            token=self.tok[who], key=key)
        private = pay("ada", "bob", "private", "a")[1]
        public = pay("bob", "ada", "public", "b")[1]
        feed = lambda who: [p["payment_id"] for p in
                            self.call("GET", "/activity", token=self.tok[who])[1]["payments"]]
        self.assertEqual(feed("ada"), [public["payment_id"], private["payment_id"], "p_1"])
        self.assertEqual(feed("bob"), [public["payment_id"], private["payment_id"], "p_1"])
        self.assertEqual(feed("cy"), [public["payment_id"], "p_1"])
        self.assertError(self.call("GET", "/activity", token=self.tok["cy"], query={"limit": "x"}),
                         422, "validation_failed")


class ConcurrencyTests(ServiceCase):
    def test_fifty_threads_draining_one_wallet(self):
        # bob has 2500: at most 25 payments of 100 can succeed.
        results = run_threads(50, lambda i: self.call(
            "POST", "/payments", {"to_handle": "cy", "amount": 100},
            token=self.tok["bob"], key=f"d{i}"))
        ok = sum(1 for status, _ in results if status == 201)
        self.assertEqual(ok, 25)
        self.assertTrue(all(s in (201, 409) for s, _ in results))
        self.assertEqual((self.balance("bob"), self.balance("cy")), (0, 2500))
        self.assertEqual(sum(self.balance(u) for u in ("ada", "bob", "cy")), 12500)

    def test_concurrent_pays_of_one_request_move_money_once(self):
        status, rq = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 1000},
                               token=self.tok["bob"], key="r")
        path = f"/requests/{rq['request_id']}/pay"
        results = run_threads(30, lambda i: self.call("POST", path, {}, token=self.tok["ada"],
                                                      key=f"p{i}"))
        statuses = sorted(r[0] for r in results)
        self.assertEqual(statuses, [201] + [409] * 29)
        self.assertEqual(self.balance("ada"), 9000)

    def test_pay_decline_cancel_race_one_winner(self):
        status, rq = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 10},
                               token=self.tok["bob"], key="r")
        rid = rq["request_id"]
        actions = [
            lambda: self.call("POST", f"/requests/{rid}/pay", {}, token=self.tok["ada"], key="p"),
            lambda: self.call("POST", f"/requests/{rid}/decline", token=self.tok["ada"]),
            lambda: self.call("POST", f"/requests/{rid}/cancel", token=self.tok["bob"]),
        ]
        results = run_threads(3, lambda i: actions[i]())
        winners = [r for r in results if r[0] in (200, 201)]
        self.assertEqual(len(winners), 1)
        final = self.call("GET", "/requests", token=self.tok["bob"])[1]["requests"][0]["status"]
        self.assertEqual(self.balance("ada"), 9990 if final == "paid" else 10000)


class HttpLoadTests(ServiceCase):
    """50 requests in flight over a real socket: no 5xx, all under 5 s (I-08)."""

    def test_fifty_in_flight_over_http(self):
        import json
        import time
        import urllib.error
        import urllib.request

        from pocketful.server import make_server

        server = make_server(0, self.store)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}"

        def one(i):
            req = urllib.request.Request(
                f"{url}/payments", method="POST",
                data=json.dumps({"to_handle": "cy", "amount": 100}).encode(),
                headers={"Authorization": f"Bearer {self.tok['bob']}",
                         "Idempotency-Key": f"h{i}"})
            start = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = resp.status
            except urllib.error.HTTPError as err:
                status = err.code
            return status, time.perf_counter() - start

        try:
            results = run_threads(50, one)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(sorted({s for s, _ in results}), [201, 409])
        self.assertLess(max(t for _, t in results), 5)
        self.assertEqual(self.balance("bob"), 0)
