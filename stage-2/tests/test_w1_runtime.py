"""W1: health, reset/fixture validation, errors, JSON edge cases, auth, /me."""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from pocketful import passwords
from pocketful.fixture import build_state
from pocketful.jsonio import canonical, encode, parse_body
from pocketful.server import make_server

from tests.helpers import ServiceCase, fixture


class ResetTests(ServiceCase):
    def test_health(self):
        self.assertEqual(self.call("GET", "/health"), (200, {"status": "ok"}))

    def test_me_after_reset(self):
        status, body = self.call("GET", "/me", token=self.tok["ada"])
        self.assertEqual(status, 200)
        self.assertEqual(body, {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
                                "balance": 10000, "currency": "EUR", "minor_units": 2})

    def test_negative_balance_rejected_and_state_kept(self):
        bad = fixture()
        bad["users"][0]["balance"] = -1
        self.assertError(self.call("POST", "/_test/reset", bad), 422, "validation_failed")
        self.assertEqual(self.balance("ada"), 10000)  # old token still works (S-12)

    def test_malformed_fixtures_are_422(self):
        mutations = [
            lambda f: f.pop("users"),
            lambda f: f.update(minor_units=1),
            lambda f: f["users"][0].update(handle="Ada!"),
            lambda f: f["users"][0].update(balance=1.5),
            lambda f: f["users"][0].update(balance=True),
            lambda f: f["users"][1].update(id="u_ada"),
            lambda f: f["users"][1].update(handle="ada"),
            lambda f: f["users"][1].update(email="ada@example.com"),
            lambda f: f["payments"][0].update(to_user_id="u_nobody"),
            lambda f: f["requests"][0].update(payer_id="u_nobody"),
            lambda f: f["requests"][0].update(status="weird"),
            lambda f: f.update(settlement_operator_ids=["u_nobody"]),
        ]
        for mutate in mutations:
            bad = fixture()
            mutate(bad)
            self.assertError(self.call("POST", "/_test/reset", bad), 422, "validation_failed")
        self.assertEqual(self.balance("ada"), 10000)

    def test_reset_body_must_be_object(self):
        self.assertError(self.call("POST", "/_test/reset", raw=b"[]"), 400, "malformed_request")
        self.assertError(self.call("POST", "/_test/reset", raw=b"{"), 400, "malformed_request")

    def test_reset_replaces_state_and_tokens(self):
        f = fixture()
        f["users"] = f["users"][:1]
        f["payments"], f["requests"], f["settlement_operator_ids"] = [], [], []
        self.assertEqual(self.call("POST", "/_test/reset", f)[0], 204)
        self.assertError(self.call("GET", "/me", token=self.tok["ada"]), 401, "unauthenticated")
        self.assertEqual(self.login("ada@example.com") is not None, True)

    def test_unknown_path_and_wrong_method(self):
        self.assertError(self.call("GET", "/nope"), 404, "not_found")
        self.assertError(self.call("DELETE", "/me", token=self.tok["ada"]), 404, "not_found")


class AuthTests(ServiceCase):
    def signup(self, email, password="long enough", name="N"):
        return self.call("POST", "/auth/signup",
                         {"email": email, "password": password, "display_name": name})

    def test_signup_then_me_and_login(self):
        status, body = self.signup("A.B-c@x.com", name="Abc")
        self.assertEqual(status, 201, body)
        self.assertEqual(set(body), {"user_id", "display_name", "token"})
        status, me = self.call("GET", "/me", token=body["token"])
        self.assertEqual((me["handle"], me["balance"]), ("a_b_c", 0))
        second = self.login("A.B-c@x.com", "long enough")
        self.assertNotEqual(second, body["token"])
        self.assertEqual(self.call("GET", "/me", token=body["token"])[0], 200)

    def test_handle_truncated_to_20(self):
        status, body = self.signup("abcdefghijklmnopqrstuvwxyz@x.com")
        self.assertEqual(self.call("GET", "/me", token=body["token"])[1]["handle"],
                         "abcdefghijklmnopqrst")

    def test_signup_errors(self):
        self.assertError(self.signup("ada@example.com"), 409, "email_taken")
        self.assertError(self.signup("Ada@other.com"), 409, "handle_taken")
        self.assertError(self.signup("nobody"), 422, "validation_failed")
        self.assertError(self.signup("@x.com"), 422, "validation_failed")
        self.assertError(self.signup("new@x.com", password="short"), 422, "validation_failed")
        self.assertError(self.call("POST", "/auth/signup", {"email": "e@x.com"}),
                         422, "validation_failed")
        self.assertError(self.call("POST", "/auth/signup",
                                   {"email": 5, "password": "long enough", "display_name": "N"}),
                         400, "malformed_request")

    def test_handle_collision_leaves_email_free(self):
        self.assertError(self.signup("ADA@x.com"), 409, "handle_taken")
        self.assertEqual(self.call("POST", "/auth/login",
                                   {"email": "ADA@x.com", "password": "long enough"})[0], 401)

    def test_login_failures(self):
        self.assertError(self.call("POST", "/auth/login",
                                   {"email": "ada@example.com", "password": "wrong pass"}),
                         401, "unauthenticated")
        self.assertError(self.call("POST", "/auth/login",
                                   {"email": "who@example.com", "password": "correct horse"}),
                         401, "unauthenticated")

    def test_bad_tokens_are_401(self):
        self.assertError(self.call("GET", "/me"), 401, "unauthenticated")
        self.assertError(self.call("GET", "/me", token="nope"), 401, "unauthenticated")
        self.assertError(self.call("GET", "/me", token="nope", raw=b"{"), 401, "unauthenticated")

    def test_concurrent_signups_same_email_one_wins(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.signup("race@x.com")[0]))
                   for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [201] + [409] * 9)

    def test_password_is_hashed(self):
        user = self.store.state.users["u_ada"]
        self.assertTrue(user.pw_hash.startswith("scrypt$"))
        self.assertNotIn("correct horse", user.pw_hash)


class JsonTests(unittest.TestCase):
    def test_non_json_constants_and_huge_ints_are_400(self):
        for raw in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}',
                    b'{"a": ' + b"9" * 5000 + b"}", b'{"a": 1e99999999999999999999999}',
                    b"\xff", b"[" * 100000):
            with self.assertRaises(Exception) as ctx:
                parse_body(raw)
            self.assertEqual(ctx.exception.code, "malformed_request")

    def test_canonical_is_type_aware_and_recursive(self):
        same = lambda a, b: canonical(parse_body(a)) == canonical(parse_body(b))
        self.assertTrue(same(b'{"a":1000,"b":"x"}', b'{ "b":"x", "a":1e3 }'))
        self.assertTrue(same(b'{"a":1000}', b'{"a":1000.0}'))
        self.assertFalse(same(b'{"a":1}', b'{"a":true}'))
        self.assertFalse(same(b'{"a":[1]}', b'{"a":[true]}'))
        self.assertFalse(same(b'{"a":0}', b'{"a":false}'))
        self.assertFalse(same(b'{}', b'{"visibility":"public"}'))
        self.assertFalse(same(b'{"a":10.5}', b'{"a":10}'))

    def test_lone_surrogate_encodes(self):
        out = encode({"note": "\ud800 ok \U0001f600"})
        self.assertEqual(json.loads(out), {"note": "\ud800 ok \U0001f600"})
        self.assertIn("😀".encode(), encode({"note": "😀"}))


class ScryptTimingTests(unittest.TestCase):
    def test_parameters(self):
        self.assertEqual((passwords.N, passwords.R, passwords.P), (2 ** 11, 8, 1))
        stored = passwords.hash_password("correct horse")
        self.assertTrue(passwords.verify_password("correct horse", stored))
        self.assertFalse(passwords.verify_password("correct horsf", stored))

    def thousand_users(self, password_of):
        f = fixture()
        f["payments"], f["requests"], f["settlement_operator_ids"] = [], [], []
        f["users"] = [{"id": f"u{i}", "email": f"u{i}@x.com", "password": password_of(i),
                       "display_name": "U", "handle": f"u{i}", "balance": 1}
                      for i in range(1000)]
        start = time.perf_counter()
        state = build_state(f)
        return state, time.perf_counter() - start

    def test_thousand_user_reset_timing_shared_password(self):
        state, elapsed = self.thousand_users(lambda i: "correct horse")
        print(f"\n1000-user fixture build, one password: {elapsed:.2f} s", flush=True)
        self.assertEqual(len({u.pw_hash for u in state.users.values()}), 1)
        self.assertLess(elapsed, 1)

    def test_thousand_user_reset_timing_distinct_passwords(self):
        state, elapsed = self.thousand_users(lambda i: f"password {i}")
        print(f"\n1000-user fixture build, distinct passwords: {elapsed:.2f} s", flush=True)
        self.assertEqual(len({u.pw_hash for u in state.users.values()}), 1000)
        self.assertLess(elapsed, 10)


class FixturePasswordTests(ServiceCase):
    """D-208: one hash per distinct fixture password; salts never shared across passwords."""

    def test_shared_password_shares_hash_and_everyone_logs_in(self):
        users = self.store.state.users
        self.assertEqual(users["u_ada"].pw_hash, users["u_bob"].pw_hash)
        for email in ("ada@example.com", "bob@example.com", "cy@example.com"):
            self.login(email)

    def test_distinct_passwords_get_distinct_salts(self):
        hashes = passwords.hash_many(["a long one", "b long one", "a long one", "c long one"])
        self.assertEqual(hashes[0], hashes[2])
        salts = {h.split("$")[4] for h in hashes}
        self.assertEqual(len(salts), 3)
        self.assertTrue(passwords.verify_password("b long one", hashes[1]))
        self.assertFalse(passwords.verify_password("a long one", hashes[1]))
        self.assertEqual(passwords.hash_many([]), [])

    def test_new_reset_uses_a_new_salt(self):
        before = self.store.state.users["u_ada"].pw_hash
        self.call("POST", "/_test/reset", fixture())
        self.assertNotEqual(self.store.state.users["u_ada"].pw_hash, before)

    def test_signup_gets_its_own_salt(self):
        status, body = self.call("POST", "/auth/signup", {"email": "dee@x.com",
                                                          "password": "correct horse",
                                                          "display_name": "Dee"})
        self.assertEqual(status, 201)
        users = self.store.state.users
        self.assertNotEqual(users[body["user_id"]].pw_hash.split("$")[4],
                            users["u_ada"].pw_hash.split("$")[4])

    def test_worker_count_respects_cgroup_quota(self):
        from unittest import mock
        with mock.patch("builtins.open", mock.mock_open(read_data="200000 100000\n")):
            self.assertEqual(passwords._quota_cpus(), 2)
        with mock.patch("builtins.open", mock.mock_open(read_data="max 100000\n")):
            self.assertIsNone(passwords._quota_cpus())
        self.assertGreaterEqual(passwords.usable_cpus(), 1)


class HttpServerTests(unittest.TestCase):
    """End to end over a real socket: content type, 204 without body, JSON 404s."""

    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def test_health_and_reset_over_http(self):
        self.assertEqual(self.server.request_queue_size >= 128, True)
        status, headers, body = self.request("GET", "/health")
        self.assertEqual((status, json.loads(body)), (200, {"status": "ok"}))
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        status, headers, body = self.request("POST", "/_test/reset", fixture())
        self.assertEqual((status, body), (204, b""))

    def test_unknown_method_and_path_are_json_404(self):
        for method in ("GET", "OPTIONS"):
            status, headers, body = self.request(method, "/nowhere")
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()


class HttpFramingTests(unittest.TestCase):
    """Auditor W1 findings 3-4: chunked bodies are decoded; short bodies are 400."""

    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def exchange(self, payload):
        import socket
        with socket.create_connection(("127.0.0.1", self.port), timeout=15) as sock:
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
        return data

    def test_handler_has_socket_timeout(self):
        self.assertEqual(self.server.RequestHandlerClass.timeout, 10)

    def test_chunked_reset_then_keepalive_request(self):
        body = json.dumps(fixture()).encode()
        payload = (b"POST /_test/reset HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"
                   + f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
                   + b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        data = self.exchange(payload)
        self.assertTrue(data.startswith(b"HTTP/1.1 204"), data[:200])
        self.assertEqual(data.count(b"HTTP/1.1 200"), 1, data)
        self.assertIn(b'{"status": "ok"}', data)

    def test_short_body_is_400(self):
        data = self.exchange(b"POST /_test/reset HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{}")
        self.assertTrue(data.startswith(b"HTTP/1.1 400"), data[:200])
        self.assertIn(b"malformed_request", data)
