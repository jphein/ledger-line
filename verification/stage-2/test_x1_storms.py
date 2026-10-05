"""X1 storms: 50 in flight, 5 repetitions each (I-200..I-203, R-234, R-205)."""
import random
from collections import Counter

import pytest

import pf
import pf2
from pf import as_, ok
from pf2 import auth_of, authorize, capture, me, void

L = pytest.mark.ledger
REPS = range(5)
WIDTH = 50


def sw():
    users = [pf.user("u_ada", "ada", 5000), pf.user("u_bob", "bob", 3000),
             pf.user("u_cy", "cy", 1000), pf.user("u_dee", "dee", 0), pf.user("u_op", "op", 0)]
    return pf.world(pf2.fixture2(users=users, payments=[], requests=[], operators=["u_op"]))


def statuses(res):
    bad = [r for r in res if isinstance(r, Exception)]
    assert not bad, f"transport errors: {bad[:3]!r}"
    return Counter(r.status_code for r in res)


def check_all(w):
    ms = {h: me(a) for h, a in w.users.items()}          # me() asserts I-201 per read
    assert sum(m["total"] for m in ms.values()) == w.total, f"I-200: {ms}"
    return ms


@L("I-200", "I-201", "R-234", "R-204", "R-203", "I-08")
@pytest.mark.parametrize("rep", REPS)
def test_mixed_holds_storm_one_wallet(rep):
    w = sw()
    rnd = random.Random(500 + rep)
    pre = [ok(authorize(w.cy, "bob", 100), 201)["authorization_id"] for _ in range(3)]
    calls = []
    for i in range(WIDTH * 2):
        k = rnd.random()
        if k < 0.25:
            to = rnd.choice(["ada", "bob", "dee"])
            calls.append(lambda c, to=to: as_(w.cy, c).pay(to, 90))
        elif k < 0.45:
            to = rnd.choice(["ada", "bob"])
            calls.append(lambda c, to=to: authorize(as_(w.cy, c), to, 120))
        elif k < 0.6:
            aid = rnd.choice(pre)
            calls.append(lambda c, aid=aid: capture(as_(w.bob, c), aid,
                                                    {"amount": 30, "final": False}))
        elif k < 0.7:
            calls.append(lambda c: as_(w.op, c).post("/settlements", {"transfers": [
                {"from_handle": "cy", "to_handle": "dee", "amount": 150},
                {"from_handle": "dee", "to_handle": "ada", "amount": 50}]}, key=pf.new_key()))
        elif k < 0.75:
            aid = rnd.choice(pre)
            calls.append(lambda c, aid=aid: void(as_(w.cy, c), aid))
        else:
            calls.append(lambda c: as_(w.cy, c).get("/me"))
    res = pf.storm(calls, WIDTH)
    st = statuses(res)
    assert set(st) <= {200, 201, 409, 422}, st
    for r in res:
        if r.request.url.path == "/me":
            m = r.json()
            assert m["available"] == m["total"] - m["held"] >= 0, f"I-201 mid-storm: {m}"
            assert m["balance"] == m["total"]
        if r.status_code == 422:
            assert r.json()["error"]["code"] == "capture_exceeds_authorization", r.text
    check_all(w)


@L("I-202", "R-205", "R-226")
@pytest.mark.parametrize("rep", REPS)
def test_concurrent_partial_captures_never_over_capture(rep):
    w = sw()
    a = ok(authorize(w.ada, "bob", 1000), 201)["authorization_id"]
    calls = [lambda c: capture(as_(w.bob, c), a, {"amount": 70, "final": False})
             for _ in range(WIDTH)]
    res = pf.storm(calls, WIDTH)
    st = statuses(res)
    n = st[201]
    assert n == 14, st                                   # 14*70 = 980 <= 1000 < 15*70
    for r in res:
        if r.status_code != 201:
            assert r.status_code == 422 and \
                r.json()["error"]["code"] == "capture_exceeds_authorization", r.text
    g = auth_of(w.ada, a)
    assert g["captured_amount"] == 980 and g["remaining_amount"] == 20
    assert len(g["payment_ids"]) == 14 and g["status"] == "open"
    m = me(w.ada)
    assert (m["total"], m["held"], m["available"]) == (4020, 20, 4000)
    check_all(w)


@L("I-202", "I-04", "R-49", "R-210")
@pytest.mark.parametrize("rep", REPS)
@pytest.mark.parametrize("kind", ["authorize", "capture"])
def test_concurrent_identical_auth_writes(rep, kind):
    w = sw()
    k = pf.new_key()
    if kind == "authorize":
        call = lambda c: authorize(as_(w.ada, c), "bob", 321, key=k)  # noqa: E731
    else:
        a = ok(authorize(w.ada, "bob", 1000), 201)["authorization_id"]
        call = lambda c: capture(as_(w.bob, c), a, {"amount": 321, "final": False}, key=k)  # noqa
    res = pf.storm([call] * WIDTH, WIDTH)
    st = statuses(res)
    assert st[201] == 1 and st[200] == WIDTH - 1, st
    assert len({r.text for r in res}) <= 2               # same JSON value; allow formatting
    assert len({str(sorted(r.json().items())) for r in res}) == 1
    m = me(w.ada)
    if kind == "authorize":
        assert m["held"] == 321 and len(pf2.auths(w.ada)) == 1
    else:
        assert m["total"] == 5000 - 321 and m["held"] == 1000 - 321
        assert sum(1 for p in w.bob.activity() if p["amount"] == 321) == 1
    check_all(w)


@L("I-203", "R-234", "R-229", "R-224")
@pytest.mark.parametrize("rep", REPS)
def test_capture_void_race(rep):
    w = sw()
    ids = [ok(authorize(w.ada, "bob", 200), 201)["authorization_id"] for _ in range(5)]
    calls, tags = [], []
    for aid in ids:
        for j in range(WIDTH // 5):
            if j % 2:
                calls.append(lambda c, aid=aid: capture(as_(w.bob, c), aid))
                tags.append((aid, "capture"))
            else:
                calls.append(lambda c, aid=aid: void(as_(w.ada, c), aid))
                tags.append((aid, "void"))
    res = pf.storm(calls, WIDTH)
    statuses(res)
    captured = 0
    for aid in ids:
        mine = [(t, r) for (a, t), r in zip(tags, res) if a == aid]
        st = auth_of(w.ada, aid)["status"]
        assert st in ("captured", "voided"), st
        caps = [r for t, r in mine if t == "capture"]
        voids = [r for t, r in mine if t == "void"]
        if st == "captured":
            assert sum(r.status_code == 201 for r in caps) == 1
            assert all(r.status_code in (201, 409) for r in caps)
            assert all(r.status_code == 409 and r.json()["error"]["code"] ==
                       "authorization_not_open" for r in voids), [v.text for v in voids]
            captured += 1
        else:
            assert all(r.status_code == 200 for r in voids), [v.text for v in voids]
            assert all(r.status_code == 409 and r.json()["error"]["code"] ==
                       "authorization_not_open" for r in caps), [c.text for c in caps]
    m = me(w.ada)
    assert m["held"] == 0 and m["total"] == 5000 - 200 * captured
    check_all(w)


@L("I-201", "R-204", "I-02")
@pytest.mark.parametrize("rep", REPS)
def test_authorize_drain_storm(rep):
    w = sw()
    calls = [lambda c: authorize(as_(w.cy, c), "bob", 30)
             for _ in range(WIDTH // 2)]
    calls += [lambda c: as_(w.cy, c).pay("bob", 30) for _ in range(WIDTH // 2)]
    res = pf.storm(calls, WIDTH)
    st = statuses(res)
    assert st[201] == 33 and st[409] == WIDTH - 33, st   # 33*30 = 990 <= 1000
    m = me(w.cy)
    assert m["available"] == 10
    check_all(w)
