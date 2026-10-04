"""W1: errors (R-21..R-30), authentication (R-31..R-40), S-04, S-05, S-14, S-15."""
from urllib.parse import quote

import pytest

import pf
from pf import Api, err, ok

L = pytest.mark.ledger


# ------------------------------------------------------------------ errors

@L("R-21", "R-22")
@pytest.mark.parametrize("raw", ["", "{", "not json", "[]", "[1,2]", "\"str\"", "42",
                                 "null", "true", "{\"to_handle\": \"bob\",}"])
def test_unparseable_or_non_object_body_400(raw):
    w = pf.world()
    err(w.ada.post("/payments", raw=raw, key=pf.new_key()), 400, "malformed_request")
    err(w.ada.post("/requests", raw=raw, key=pf.new_key()), 400, "malformed_request")
    err(Api().post("/auth/signup", raw=raw), 400, "malformed_request")
    err(Api().post("/auth/login", raw=raw), 400, "malformed_request")
    assert w.ada.balance() == 10000


@L("R-22", "S-04", "D-03")
@pytest.mark.parametrize("val", ["5", "true", "null", "[\"bob\"]", "{\"h\": \"bob\"}"])
def test_wrong_type_handle_400(val):
    w = pf.world()
    err(w.ada.post("/payments", raw='{"to_handle": %s, "amount": 10}' % val,
                   key=pf.new_key()), 400, "malformed_request")
    err(w.ada.post("/requests", raw='{"payer_handle": %s, "amount": 10}' % val,
                   key=pf.new_key()), 400, "malformed_request")


@L("R-22", "D-03")
def test_wrong_type_auth_fields_400():
    err(Api().post("/auth/signup", {"email": 5, "password": "12345678",
                                    "display_name": "x"}), 400, "malformed_request")
    err(Api().post("/auth/signup", {"email": "t@x.com", "password": 12345678,
                                    "display_name": "x"}), 400, "malformed_request")
    err(Api().post("/auth/signup", {"email": "t@x.com", "password": "12345678",
                                    "display_name": ["x"]}), 400, "malformed_request")
    err(Api().post("/auth/login", {"email": None, "password": pf.PW}), 400,
        "malformed_request")


@L("R-23", "S-05")
def test_missing_or_empty_key_400():
    w = pf.world()
    body = {"to_handle": "bob", "amount": 10}
    err(w.ada.post("/payments", body), 400, "missing_idempotency_key")
    err(w.ada.post("/payments", body, key=""), 400, "missing_idempotency_key")
    err(w.ada.post("/requests", {"payer_handle": "bob", "amount": 10}), 400,
        "missing_idempotency_key")
    err(w.ada.post("/requests/rq_1/pay", {}), 400, "missing_idempotency_key")
    assert w.ada.balance() == 10000


@L("R-29", "S-05")
def test_key_length_bounds():
    w = pf.world()
    ok(w.ada.pay("bob", 1, key="k"), 201)
    ok(w.ada.pay("bob", 1, key="x" * 255), 201)
    err(w.ada.pay("bob", 1, key="y" * 256), 422, "validation_failed")
    err(w.ada.pay("bob", 1, key="z" * 1000), 422, "validation_failed")
    assert w.ada.balance() == 10000 - 2


@L("R-24", "S-15")
@pytest.mark.parametrize("hdr", [None, "", "Bearer", "Bearer nope",
                                 "Basic YWRhOmNvcnJlY3QgaG9yc2U=", "bearer-x", "Token abc"])
def test_bad_tokens_401(hdr):
    w = pf.world()
    h = {} if hdr is None else {"Authorization": hdr}
    a = Api()
    for method, path, body in [("GET", "/me", None), ("GET", "/activity", None),
                               ("GET", "/requests", None),
                               ("POST", "/payments", {"to_handle": "bob", "amount": 1}),
                               ("POST", "/requests", {"payer_handle": "bob", "amount": 1}),
                               ("POST", "/requests/rq_1/pay", {}),
                               ("POST", "/requests/rq_1/decline", {}),
                               ("POST", "/requests/rq_1/cancel", {}),
                               ("POST", "/splits", {"amount": 1, "participant_handles": ["bob"]}),
                               ("POST", "/settlements", {"transfers": []})]:
        kw = {"headers": h, "key": pf.new_key()}
        r = a.request(method, path, body, **kw) if body is not None else a.request(method, path, **kw)
        err(r, 401, "unauthenticated")
    assert w.ada.balance() == 10000


@L("S-15", "D-02")
def test_auth_checked_before_everything():
    w = pf.world()
    bad = Api("not-a-token")
    err(bad.post("/payments", raw="{", key=pf.new_key()), 401, "unauthenticated")
    err(bad.post("/payments", {"to_handle": "bob", "amount": -1}), 401, "unauthenticated")
    err(bad.post("/requests/does-not-exist/pay", {}, key=pf.new_key()), 401,
        "unauthenticated")
    err(bad.get("/requests?limit=0"), 401, "unauthenticated")
    err(bad.get("/activity?direction=sideways&limit=abc"), 401, "unauthenticated")
    # a token for a different user's string with a suffix
    err(Api(w.ada.token + "x").get("/me"), 401, "unauthenticated")


@L("R-26")
def test_missing_required_fields_422():
    w = pf.world()
    err(w.ada.post("/payments", {"amount": 10}, key=pf.new_key()), 422, "validation_failed")
    err(w.ada.post("/payments", {"to_handle": "bob"}, key=pf.new_key()), 422,
        "validation_failed")
    err(w.ada.post("/payments", {}, key=pf.new_key()), 422, "validation_failed")
    err(w.ada.post("/requests", {"amount": 10}, key=pf.new_key()), 422, "validation_failed")
    err(w.ada.post("/requests", {"payer_handle": "bob"}, key=pf.new_key()), 422,
        "validation_failed")
    err(Api().post("/auth/signup", {"password": "12345678", "display_name": "x"}), 422,
        "validation_failed")
    err(Api().post("/auth/signup", {"email": "m@x.com", "display_name": "x"}), 422,
        "validation_failed")
    err(Api().post("/auth/signup", {"email": "m@x.com", "password": "12345678"}), 422,
        "validation_failed")
    err(Api().post("/auth/login", {"email": "ada@example.com"}), 422, "validation_failed")
    err(Api().post("/auth/login", {"password": pf.PW}), 422, "validation_failed")
    assert w.ada.balance() == 10000


@L("R-27", "S-04")
@pytest.mark.parametrize("field,raw", [("note", "null"), ("note", "5"), ("note", "true"),
                                       ("note", "[]"), ("note", "{}"),
                                       ("visibility", "null"), ("visibility", "\"PUBLIC\""),
                                       ("visibility", "\"\""), ("visibility", "1"),
                                       ("visibility", "\"friends\""), ("visibility", "true")])
def test_note_visibility_invalid_422(field, raw):
    w = pf.world()
    body = '{"to_handle": "bob", "amount": 10, "%s": %s}' % (field, raw)
    err(w.ada.post("/payments", raw=body, key=pf.new_key()), 422, "validation_failed")
    if field == "note":
        body = '{"payer_handle": "bob", "amount": 10, "note": %s}' % raw
        err(w.ada.post("/requests", raw=body, key=pf.new_key()), 422, "validation_failed")
    else:
        err(w.ada.post("/requests/rq_1/pay", raw='{"visibility": %s}' % raw,
                       key=pf.new_key()), 422, "validation_failed")
    assert w.ada.balance() == 10000


@L("R-28", "R-29", "R-72", "R-73")
@pytest.mark.parametrize("q", ["limit=1e9", "limit=4.0", "limit=" + quote("+4"),
                               "limit=-1", "limit=0", "limit=201", "limit=abc",
                               "limit=1000000000000000000000", "limit=%204",
                               "offset=-1", "offset=1.0", "offset=" + quote("+0"),
                               "offset=1e1", "offset=x", "limit=0x10", "limit=" + quote("٣")])
def test_bad_integer_query_422(q):
    w = pf.world()
    err(w.ada.get(f"/activity?{q}"), 422, "validation_failed")
    err(w.ada.get(f"/requests?{q}"), 422, "validation_failed")


@L("R-29", "R-72", "R-73")
@pytest.mark.parametrize("q", ["limit=1", "limit=200", "offset=0", "offset=999999",
                               "limit=007", "limit=50&offset=0"])
def test_good_integer_query_200(q):
    w = pf.world()
    ok(w.ada.get(f"/activity?{q}"))
    ok(w.ada.get(f"/requests?{q}"))


# ------------------------------------------------------------------ auth

def signup(email, password="12345678", name="Someone"):
    return Api().post("/auth/signup", {"email": email, "password": password,
                                       "display_name": name})


@L("R-31", "R-52")
def test_signup_201_shape_and_token():
    pf.world()
    r = signup("carol@example.org", name="Carol ✨")
    b = ok(r, 201)
    assert set(b) >= {"user_id", "display_name", "token"}
    assert b["display_name"] == "Carol ✨"
    assert isinstance(b["token"], str) and b["token"]
    pf.check_id(b["user_id"])
    me = Api(b["token"]).me()
    assert me == {"user_id": b["user_id"], "display_name": "Carol ✨", "handle": "carol",
                  "balance": 0, "currency": "EUR", "minor_units": 2}


@L("R-32")
def test_login_200_shape():
    pf.world()
    s = ok(signup("dave@example.org", password="longenough", name="Dave"), 201)
    b = ok(Api().post("/auth/login", {"email": "dave@example.org",
                                      "password": "longenough"}), 200)
    assert b["user_id"] == s["user_id"] and b["display_name"] == "Dave"
    assert Api(b["token"]).me()["user_id"] == s["user_id"]
    seeded = ok(Api().post("/auth/login", {"email": "ada@example.com", "password": pf.PW}))
    assert seeded["user_id"] == "u_ada" and seeded["display_name"] == "Ada"


@L("R-33")
def test_email_taken_409():
    pf.world()
    ok(signup("erin@example.org"), 201)
    err(signup("erin@example.org", password="differentpw"), 409, "email_taken")
    err(signup("ada@example.com"), 409, "email_taken")


@L("R-34")
def test_password_length_boundary():
    pf.world()
    err(signup("p7@example.org", password="1234567"), 422, "validation_failed")
    err(signup("p0@example.org", password=""), 422, "validation_failed")
    err(signup("p7u@example.org", password="ééééééé"), 422, "validation_failed")
    ok(signup("p8@example.org", password="12345678"), 201)
    ok(signup("p8u@example.org", password="éééééééé"), 201)


@L("R-35")
@pytest.mark.parametrize("email", ["plainaddress", "@example.com", "user@", "", "@",
                                   "user.example.com"])
def test_email_format_422(email):
    pf.world()
    err(signup(email), 422, "validation_failed")


@L("R-36")
def test_login_failures_401():
    pf.world()
    err(Api().post("/auth/login", {"email": "ada@example.com", "password": "wrong pass"}),
        401, "unauthenticated")
    err(Api().post("/auth/login", {"email": "ghost@example.com", "password": pf.PW}),
        401, "unauthenticated")
    err(Api().post("/auth/login", {"email": "ada@example.com", "password": ""}),
        401, "unauthenticated")


@L("R-37", "S-14")
def test_handle_taken_creates_nothing():
    pf.world()
    err(signup("ada@other.org"), 409, "handle_taken")
    err(Api().post("/auth/login", {"email": "ada@other.org", "password": "12345678"}),
        401, "unauthenticated")
    # still no account: same email again gives handle_taken, not email_taken
    err(signup("ada@other.org"), 409, "handle_taken")
    ok(signup("ada2@other.org"), 201)


@L("R-14", "S-14")
@pytest.mark.parametrize("email,handle", [
    ("A.B-c@x.com", "a_b_c"),
    ("UPPER@x.com", "upper"),
    ("abcdefghijklmnopqrstuvwxyz@x.com", "abcdefghijklmnopqrst"),
    ("a+tag@x.com", "a_tag"),
    ("under_score9@x.com", "under_score9"),
    ("José.Ñ@x.com", "jos___"),
    ("x.y.z.w.v.u.t.s.r.q.p.o@x.com", "x_y_z_w_v_u_t_s_r_q_"),
    ("12345@x.com", "12345"),
])
def test_derived_handle(email, handle):
    pf.world()
    b = ok(signup(email), 201)
    assert Api(b["token"]).me()["handle"] == handle


@L("R-14", "S-14", "R-37")
def test_derived_collision_after_truncation():
    pf.world()
    ok(signup("abcdefghijklmnopqrstuvwxyz@x.com"), 201)
    err(signup("abcdefghijklmnopqrstUVW@y.com"), 409, "handle_taken")
    ok(signup("a-b@x.com"), 201)
    err(signup("a.b@x.com"), 409, "handle_taken")
    err(signup("A_B@z.com"), 409, "handle_taken")


@L("R-38")
def test_public_endpoints_need_no_token():
    pf.world()
    ok(Api().get("/health"))
    ok(Api().post("/auth/login", {"email": "ada@example.com", "password": pf.PW}))
    ok(signup("pub@example.org"), 201)
    assert Api().post("/_test/reset", pf.fixture()).status_code == 204


@L("R-38", "R-84")
def test_export_import_need_no_token():
    pf.world()
    exp = ok(Api().get("/_test/export"))
    assert Api().post("/_test/import", exp).status_code == 204


@L("R-39")
def test_multiple_tokens_all_valid():
    pf.world()
    s = ok(signup("multi@example.org"), 201)
    t = [s["token"]]
    for _ in range(3):
        t.append(ok(Api().post("/auth/login", {"email": "multi@example.org",
                                              "password": "12345678"}))["token"])
    assert len(set(t)) == 4, "each login must issue a new token"
    for tok in t:
        assert Api(tok).me()["handle"] == "multi"
    a1 = pf.login("ada@example.com")
    a2 = pf.login("ada@example.com")
    assert a1.token != a2.token
    ok(a1.pay("bob", 1), 201)
    assert a2.balance() == 9999


@L("R-40")
def test_export_has_no_plaintext_passwords():
    pf.world()
    ok(signup("secretive@example.org", password="Zebra-Plaintext-77"), 201)
    r = Api().get("/_test/export")
    ok(r)
    assert "Zebra-Plaintext-77" not in r.text
    assert pf.PW not in r.text
