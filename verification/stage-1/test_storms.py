"""Invariant storms: 50 in flight, each storm repeated 5 times (I-01..I-08, S-01, S-02).

Every request in a storm goes through pf.Api, which records any 5xx or >5 s response
against R-30 / R-05 / I-08.
"""
import json
import random
from collections import Counter

import pytest

import pf
from pf import as_, ok

L = pytest.mark.ledger
REPS = range(5)
WIDTH = 50


def storm_world():
    users = [pf.user("u_ada", "ada", 5000), pf.user("u_bob", "bob", 3000),
             pf.user("u_cy", "cy", 1000), pf.user("u_dee", "dee", 0),
             pf.user("u_eve", "eve", 777), pf.user("u_op", "op", 0)]
    return pf.world(pf.fixture(users=users, payments=[], requests=[], operators=["u_op"]))


def statuses(results):
    bad = [r for r in results if isinstance(r, Exception)]
    assert not bad, f"transport errors: {bad[:3]!r}"
    return Counter(r.status_code for r in results)


def assert_conserved(w):
    bals = {h: a.balance() for h, a in w.users.items()}
    assert sum(bals.values()) == w.total, f"I-01: {bals} sum != {w.total}"
    assert min(bals.values()) >= 0, f"I-02 negative: {bals}"
    return bals


def assert_feed_matches_balances(w, start):
    """I-05: every payment in both parties' feeds, and balances explained by feeds."""
    feeds = {h: {p["payment_id"]: p for p in a.activity()} for h, a in w.users.items()}
    all_p = {}
    for f in feeds.values():
        all_p.update(f)
    delta = Counter()
    for pid, p in all_p.items():
        assert pid in feeds[p["from_handle"]], f"{pid} missing from sender feed"
        assert pid in feeds[p["to_handle"]], f"{pid} missing from receiver feed"
        delta[p["from_handle"]] -= p["amount"]
        delta[p["to_handle"]] += p["amount"]
    for h, a in w.users.items():
        assert a.balance() == start[h] + delta[h], f"I-05 {h}: balance vs feed mismatch"


@L("I-01", "I-02", "I-05", "I-08", "R-61", "R-05", "R-30", "S-01")
@pytest.mark.parametrize("rep", REPS)
def test_mixed_payment_storm(rep):
    w = storm_world()
    rnd = random.Random(1000 + rep)
    start = {u["handle"]: u["balance"] for u in w.fixture["users"]}
    hs = ["ada", "bob", "cy", "dee", "eve"]
    pending = [ok(w.users[rnd.choice([x for x in hs[:3] if x != h])]
                  .ask(h, rnd.randint(1, 900)), 201)
               for h in hs for _ in range(2)]
    calls = []
    for i in range(WIDTH * 3):
        kind = rnd.random()
        if kind < 0.55:
            f, to = rnd.sample(hs, 2)
            amt = rnd.choice([1, 50, 333, 999, 2500, 6000])
            calls.append(lambda c, f=f, to=to, amt=amt: as_(w.users[f], c).pay(to, amt))
        elif kind < 0.75 and pending:
            q = rnd.choice(pending)
            calls.append(lambda c, q=q: as_(w.users[q["payer_handle"]], c)
                         .pay_request(q["request_id"]))
        elif kind < 0.85:
            q = rnd.choice(pending)
            calls.append(lambda c, q=q: as_(w.users[q["payer_handle"]], c)
                         .post(f"/requests/{q['request_id']}/decline", {}))
        elif kind < 0.92:
            h = rnd.choice(hs)
            calls.append(lambda c, h=h: as_(w.users[h], c).get("/me"))
        else:
            h = rnd.choice(hs)
            calls.append(lambda c, h=h: as_(w.users[h], c).get("/activity?limit=20"))
    res = storm(calls)
    st = statuses(res)
    assert set(st) <= {200, 201, 409}, st
    for r in res:
        if r.request.url.path == "/me":
            assert r.json()["balance"] >= 0, "I-02: negative balance observed mid-storm"
    assert_conserved(w)
    assert_feed_matches_balances(w, start)


def storm(calls):
    return pf.storm(calls, WIDTH)


@L("I-02", "R-55", "I-08")
@pytest.mark.parametrize("rep", REPS)
def test_drain_one_wallet(rep):
    w = storm_world()
    amt = 30                                    # cy has 1000 -> at most 33 can succeed
    targets = ["ada", "bob", "dee", "eve"]
    calls = [lambda c, i=i: as_(w.cy, c).pay(targets[i % 4], amt) for i in range(WIDTH)]
    res = storm(calls)
    st = statuses(res)
    assert set(st) <= {201, 409}, st
    assert st[201] == 33, st
    for r in res:
        if r.status_code == 409:
            assert r.json()["error"]["code"] == "insufficient_funds"
    assert w.cy.balance() == 1000 - 33 * amt
    assert_conserved(w)


@L("I-02", "R-68", "I-08")
@pytest.mark.parametrize("rep", REPS)
def test_drain_via_request_pays(rep):
    w = storm_world()
    qs = [ok(w.ada.ask("eve", 100), 201)["request_id"] for _ in range(WIDTH)]
    calls = [lambda c, q=q: as_(w.eve, c).pay_request(q) for q in qs]
    st = statuses(storm(calls))
    assert st[201] == 7 and st[409] == WIDTH - 7, st
    assert w.eve.balance() == 77
    assert len(w.eve.requests("status=paid")) == 7
    assert len(w.eve.requests("status=pending")) == WIDTH - 7
    assert_conserved(w)


@L("I-03", "R-68", "I-08")
@pytest.mark.parametrize("rep", REPS)
def test_one_request_many_pays(rep):
    w = storm_world()
    q = ok(w.bob.ask("ada", 1200), 201)["request_id"]
    calls = [lambda c: as_(w.ada, c).pay_request(q) for _ in range(WIDTH)]
    res = storm(calls)
    st = statuses(res)
    assert st[201] == 1 and st[409] == WIDTH - 1, st
    for r in res:
        if r.status_code == 409:
            assert r.json()["error"]["code"] == "request_not_pending"
    assert w.ada.balance() == 3800 and w.bob.balance() == 4200
    paid = [x for x in w.ada.activity() if x["request_id"] == q]
    assert len(paid) == 1
    assert_conserved(w)


@L("I-04", "R-49", "R-45", "I-08")
@pytest.mark.parametrize("rep", REPS)
@pytest.mark.parametrize("kind", ["payment", "request", "pay", "split", "settlement"])
def test_concurrent_identical_requests(rep, kind):
    w = storm_world()
    k = pf.new_key()
    if kind == "payment":
        call = lambda c: as_(w.ada, c).pay("bob", 123, key=k, note="once")  # noqa: E731
    elif kind == "request":
        call = lambda c: as_(w.ada, c).ask("bob", 123, key=k)  # noqa: E731
    elif kind == "pay":
        q = ok(w.bob.ask("ada", 123), 201)["request_id"]
        call = lambda c: as_(w.ada, c).pay_request(q, {"visibility": "private"}, key=k)  # noqa
    elif kind == "split":
        body = {"amount": 30, "participant_handles": ["bob", "cy"]}
        call = lambda c: as_(w.ada, c).post("/splits", body, key=k)  # noqa: E731
    else:
        body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 123}]}
        call = lambda c: as_(w.op, c).post("/settlements", body, key=k)  # noqa: E731
    res = storm([call] * WIDTH)
    st = statuses(res)
    assert st[201] == 1 and st[200] == WIDTH - 1, st
    bodies = {json.dumps(r.json(), sort_keys=True) for r in res}
    assert len(bodies) == 1, "replays must carry the original body"
    if kind in ("payment", "pay", "settlement"):
        assert w.ada.balance() == 5000 - 123 and w.bob.balance() == 3000 + 123
        assert sum(1 for p in w.bob.activity() if p["amount"] == 123) == 1
    elif kind == "request":
        assert len(w.bob.requests()) == 1
    else:
        assert len(w.bob.requests()) == 1 and len(w.cy.requests()) == 1
    assert_conserved(w)


@L("I-04", "R-46", "R-49")
@pytest.mark.parametrize("rep", REPS)
def test_concurrent_same_key_conflicting_bodies(rep):
    w = storm_world()
    k = pf.new_key()
    calls = [lambda c, i=i: as_(w.ada, c).pay("bob", 10 + (i % 2), key=k)
             for i in range(WIDTH)]
    res = storm(calls)
    st = statuses(res)
    assert st[201] == 1, st
    winner = next(r for r in res if r.status_code == 201).json()
    for r in res:
        if r.status_code == 200:
            assert r.json() == winner
        elif r.status_code == 409:
            assert r.json()["error"]["code"] == "idempotency_key_reuse"
        else:
            assert r.status_code == 201
    assert w.ada.balance() == 5000 - winner["amount"]
    assert_conserved(w)


@L("I-06", "R-70", "R-71", "I-03")
@pytest.mark.parametrize("rep", REPS)
def test_pay_decline_cancel_race(rep):
    w = storm_world()
    n_req = 5
    qs = [ok(w.bob.ask("ada", 100), 201)["request_id"] for _ in range(n_req)]
    calls, tags = [], []
    for q in qs:
        for j in range(WIDTH // n_req):
            m = j % 3
            if m == 0:
                calls.append(lambda c, q=q: as_(w.ada, c).pay_request(q))
            elif m == 1:
                calls.append(lambda c, q=q: as_(w.ada, c).post(f"/requests/{q}/decline", {}))
            else:
                calls.append(lambda c, q=q: as_(w.bob, c).post(f"/requests/{q}/cancel", {}))
            tags.append((q, ("pay", "decline", "cancel")[m]))
    res = storm(calls)
    statuses(res)
    final = {x["request_id"]: x for x in w.ada.requests()}
    paid = 0
    for q in qs:
        mine = [(tag, r) for (qq, tag), r in zip(tags, res) if qq == q]
        state = final[q]["status"]
        assert state in ("paid", "declined", "cancelled"), state
        wins = {"paid": ("pay", 201), "declined": ("decline", 200),
                "cancelled": ("cancel", 200)}[state]
        for tag, r in mine:
            if tag == wins[0]:
                if state == "paid":
                    assert r.status_code in (201, 409), r.text
                else:
                    assert r.status_code == 200, (state, tag, r.text)
                    assert r.json()["status"] == state
            else:
                assert r.status_code == 409, (state, tag, r.status_code, r.text)
                assert r.json()["error"]["code"] == "request_not_pending"
        if state == "paid":
            assert sum(1 for t, r in mine if t == "pay" and r.status_code == 201) == 1
            assert final[q]["payment_id"] is not None
            paid += 1
        else:
            assert final[q]["payment_id"] is None
    assert w.ada.balance() == 5000 - 100 * paid
    assert_conserved(w)


@L("I-01", "I-02", "R-96", "R-97", "I-08")
@pytest.mark.parametrize("rep", REPS)
def test_settlement_storm(rep):
    w = storm_world()
    rnd = random.Random(7000 + rep)
    hs = ["ada", "bob", "cy", "dee", "eve"]
    start = {u["handle"]: u["balance"] for u in w.fixture["users"]}
    calls = []
    for i in range(WIDTH):
        transfers = []
        for _ in range(rnd.randint(1, 4)):
            f, to = rnd.sample(hs, 2)
            transfers.append({"from_handle": f, "to_handle": to,
                              "amount": rnd.choice([10, 400, 900, 2000])})
        if i % 2:
            f, to = rnd.sample(hs, 2)
            calls.append(lambda c, f=f, to=to: as_(w.users[f], c).pay(to, 700))
        else:
            calls.append(lambda c, tr=transfers: as_(w.op, c).post(
                "/settlements", {"transfers": tr}, key=pf.new_key()))
    res = storm(calls)
    st = statuses(res)
    assert set(st) <= {201, 409}, st
    assert_conserved(w)
    assert_feed_matches_balances(w, start)
    for r in res:
        if r.status_code == 201 and "settlement_id" in r.json() and "payments" in r.json():
            body = r.json()
            assert {p["created_at"] for p in body["payments"]} == {body["committed_at"]}


@L("I-05", "I-01")
@pytest.mark.parametrize("rep", REPS)
def test_ping_pong_storm(rep):
    """Two wallets paying each other with small balances: no lost update."""
    w = storm_world()
    start = {u["handle"]: u["balance"] for u in w.fixture["users"]}
    calls = [(lambda c: as_(w.cy, c).pay("dee", 40)) if i % 2 else
             (lambda c: as_(w.dee, c).pay("cy", 40)) for i in range(WIDTH)]
    statuses(storm(calls))
    assert_conserved(w)
    assert_feed_matches_balances(w, start)


@L("I-07", "R-88", "R-85")
@pytest.mark.parametrize("rep", REPS)
def test_export_during_storm_is_consistent(rep):
    w = storm_world()
    calls = [lambda c, i=i: as_(w.ada if i % 2 else w.bob, c).pay(
        "cy" if i % 3 else "dee", 7) for i in range(WIDTH - 5)]
    for _ in range(5):
        calls.append(lambda c: pf.Api(client=c).get("/_test/export"))
    res = storm(calls)
    statuses(res)
    exports = [r for r in res if r.request.url.path == "/_test/export"]
    assert len(exports) == 5
    after = {h: a.balance() for h, a in w.users.items()}
    for e in exports:
        assert e.status_code == 200
        r = pf.Api().post("/_test/import", e.json())
        assert r.status_code == 204, r.text
        bals = assert_conserved(w)       # every snapshot is internally consistent
        assert_feed_matches_balances(w, {u["handle"]: u["balance"]
                                         for u in w.fixture["users"]})
        assert bals["ada"] + bals["bob"] + bals["cy"] + bals["dee"] == \
            5000 + 3000 + 1000
    assert after["cy"] + after["dee"] == 1000 + 7 * (WIDTH - 5)


@L("I-08", "S-02", "R-31", "R-32", "S-01")
@pytest.mark.parametrize("rep", REPS)
def test_login_signup_storm(rep):
    storm_world()
    calls = []
    for i in range(WIDTH):
        if i % 2:
            calls.append(lambda c: pf.Api(client=c).post(
                "/auth/login", {"email": "ada@example.com", "password": pf.PW}))
        else:
            calls.append(lambda c, i=i: pf.Api(client=c).post(
                "/auth/signup", {"email": f"s{rep}_{i}@x.com", "password": "12345678",
                                 "display_name": "S"}))
    res = storm(calls)
    st = statuses(res)
    assert st[200] == WIDTH // 2 and st[201] == WIDTH // 2, st
    toks = {r.json()["token"] for r in res}
    assert len(toks) == WIDTH


@L("R-33", "R-37", "I-08")
@pytest.mark.parametrize("rep", REPS)
def test_duplicate_signup_storm(rep):
    storm_world()
    calls = [lambda c, i=i: pf.Api(client=c).post(
        "/auth/signup", {"email": "dup@x.com" if i % 2 else f"dup@y{i}.com",
                         "password": "12345678", "display_name": "D"})
        for i in range(WIDTH)]
    res = storm(calls)
    st = statuses(res)
    assert st[201] == 1 and st[409] == WIDTH - 1, st


@L("I-08", "R-05", "S-01")
@pytest.mark.parametrize("rep", REPS)
def test_read_storm_latency(rep):
    w = storm_world()
    for _ in range(20):
        ok(w.ada.pay("bob", 1), 201)
    paths = ["/me", "/activity?limit=200", "/requests?limit=200", "/health"]
    calls = [lambda c, i=i: as_(w.users[["ada", "bob", "cy", "dee"][i % 4]], c)
             .get(paths[i % 4]) for i in range(WIDTH)]
    st = statuses(storm(calls))
    assert set(st) == {200}, st
