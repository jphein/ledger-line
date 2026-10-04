"""W1: delivery, runtime, reset, conventions (R-01..R-10, R-30, S-12, S-16)."""
from pathlib import Path

import pytest

import pf
from pf import Api, err, ok

L = pytest.mark.ledger
STAGE = Path(__file__).resolve().parents[2] / "stage-1"


@L("R-01")
def test_delivery_files_present():
    assert (STAGE / "Dockerfile").is_file(), "stage-1/Dockerfile missing"
    run = STAGE / "RUN.md"
    assert run.is_file(), "stage-1/RUN.md missing"
    text = run.read_text()
    assert "docker" in text and "build" in text, "RUN.md must give a build+start command"


@L("R-04")
def test_health_exact():
    r = Api().get("/health")
    assert ok(r) == {"status": "ok"}


@L("R-06", "S-16")
def test_reset_204_no_body_no_auth():
    r = Api().post("/_test/reset", pf.fixture())
    assert r.status_code == 204
    assert r.content == b""


@L("R-06")
def test_reset_replaces_state_entirely():
    w = pf.world()
    old_token = w.ada.token
    ok(w.ada.pay("bob", 100), 201)
    # second fixture: ada absent, a different user present
    other = pf.user("u_zed", "zed", 42)
    pf.reset(pf.fixture(users=[other, pf.BOB], payments=[], requests=[]))
    err(Api(old_token).get("/me"), 401, "unauthenticated")
    err(Api().post("/auth/login", {"email": "ada@example.com", "password": pf.PW}),
        401, "unauthenticated")
    zed = pf.login("zed@example.com")
    assert zed.balance() == 42
    bob = pf.login("bob@example.com")
    assert bob.balance() == 2500
    assert bob.activity() == []
    assert bob.requests() == []


@L("R-06")
def test_repeated_resets_are_idempotent():
    for _ in range(3):
        pf.reset(pf.fixture())
    w = pf.world()
    assert w.ada.balance() == 10000
    ids = sorted(p["payment_id"] for p in w.ada.activity())
    assert ids == ["p_1"], ids  # p_2 is private between bob and cy


@L("R-06", "S-02", "R-05")
def test_large_fixture_reset_under_10s_and_logins():
    users = [pf.user(f"u_{i}", f"h{i}", 1000) for i in range(500)]
    r = Api().post("/_test/reset", pf.fixture(users=users, payments=[], requests=[]),
                   budget=10.0)
    assert r.status_code == 204, r.text
    assert pf.login("h499@example.com").balance() == 1000


@L("R-07", "S-16")
def test_content_type_on_success_and_error():
    w = pf.world()
    for r in (Api().get("/health"), w.ada.get("/me"), Api().get("/me"),
              w.ada.get("/no/such/path")):
        ct = r.headers.get("content-type", "")
        assert ct.replace(" ", "").lower() == "application/json;charset=utf-8", ct


@L("R-08")
def test_timestamps_rfc3339_with_offset():
    w = pf.world()
    p = ok(w.ada.pay("bob", 1), 201)
    assert pf.RFC3339.match(p["created_at"]), p["created_at"]
    q = ok(w.ada.ask("bob", 1), 201)
    assert pf.RFC3339.match(q["created_at"]), q["created_at"]
    for item in w.ada.activity() + w.ada.requests():
        assert pf.RFC3339.match(item["created_at"]), item


@L("R-09")
def test_unknown_body_fields_ignored():
    w = pf.world()
    p = ok(w.ada.pay("bob", 10, zzz=1, nested={"a": [1]}, request_id="x"), 201)
    assert p["amount"] == 10 and p["request_id"] is None
    ok(w.ada.ask("bob", 10, foo="bar"), 201)
    ok(Api().post("/auth/signup", {"email": "new1@x.com", "password": "12345678",
                                   "display_name": "N", "handle": "ignored", "x": 1}), 201)
    ok(Api().post("/auth/login", {"email": "ada@example.com", "password": pf.PW,
                                  "remember": True}), 200)


@L("R-09")
def test_unknown_query_params_ignored():
    w = pf.world()
    a = ok(w.ada.get("/activity?foo=bar&limit=5"))
    assert set(a) >= {"payments", "has_more"}
    ok(w.ada.get("/requests?zzz=1&page=-3"))
    ok(w.ada.get("/me?x=1"))
    ok(Api().get("/health?x=1"))


@L("R-10")
def test_ids_are_short_strings():
    w = pf.world()
    p = ok(w.ada.pay("bob", 1), 201)
    q = ok(w.ada.ask("bob", 1), 201)
    s = ok(Api().post("/auth/signup", {"email": "idlen@x.com", "password": "12345678",
                                       "display_name": "I"}), 201)
    for v in (p["payment_id"], q["request_id"], s["user_id"], w.ada.me()["user_id"]):
        assert isinstance(v, str) and 1 <= len(v) <= 64, v


@L("R-30", "D-09")
def test_unknown_path_and_method_404():
    w = pf.world()
    err(w.ada.get("/nope"), 404, "not_found")
    err(w.ada.post("/nope", {}), 404, "not_found")
    err(w.ada.get("/payments"), 404, "not_found")
    err(w.ada.request("DELETE", "/me"), 404, "not_found")


@L("R-30")
def test_garbage_never_5xx():
    w = pf.world()
    junk = [b"", b"{", b"null", b"[]", b"\"x\"", b"\xff\xfe", b"{\"amount\":1e999}",
            b"{\"to_handle\":\"bob\",\"amount\":1e400}", b"{" * 2000, b"1" * 5000]
    for path in ("/payments", "/requests", "/requests/rq_1/pay", "/auth/signup",
                 "/auth/login", "/requests/rq_1/decline"):
        for body in junk:
            r = w.ada.post(path, raw=body, key=pf.new_key())
            assert r.status_code < 500, (path, body[:20], r.status_code)
