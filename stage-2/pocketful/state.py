"""Owns the in-memory service state and the single global lock (D-01).

Every handler that reads and then writes state does both inside one
`with store.lock:` block. Reset and import build a complete new State outside
the lock and swap it in under the lock, so a rejected one changes nothing.
"""
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

DEFAULT_TTL_SECONDS = 600


def now_rfc3339():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_us():
    """Wall clock in integer microseconds, used for authorization expiry."""
    return time.time_ns() // 1000


def parse_rfc3339_us(text):
    """RFC 3339 timestamp with an explicit offset -> epoch microseconds, else ValueError."""
    if not isinstance(text, str) or "T" not in text.upper():
        raise ValueError("not an RFC 3339 timestamp")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("timestamp needs an explicit offset")
    delta = moment - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


class User:
    __slots__ = ("id", "email", "handle", "display_name", "pw_hash", "balance")

    def __init__(self, id, email, handle, display_name, pw_hash, balance):
        self.id = id
        self.email = email
        self.handle = handle
        self.display_name = display_name
        self.pw_hash = pw_hash
        self.balance = balance


class State:
    def __init__(self, currency="EUR", minor_units=2):
        self.currency = currency
        self.minor_units = minor_units
        self.users = {}          # user id -> User
        self.by_handle = {}      # handle -> user id
        self.by_email = {}       # email -> user id
        self.tokens = {}         # bearer token -> user id
        self.operators = set()   # settlement operator user ids
        self.payments = {}       # payment id -> payment body (dict)
        self.payment_log = []    # payment ids, oldest first
        self.requests = {}       # request id -> request record (dict)
        self.request_log = []    # request ids, oldest first
        self.splits = {}         # split id -> split response body
        self.settlements = {}    # settlement id -> settlement response body
        self.idempotency = {}    # (user id, method, path, key) -> (canonical body, response)
        self.counter = 0         # id sequence; skips ids already taken (R-90)
        self.ttl_seconds = DEFAULT_TTL_SECONDS
        self.authorizations = {}      # authorization id -> response-shaped record (dict)
        self.authorization_log = []   # authorization ids, oldest first
        self.expiry_us = {}           # authorization id -> expires_at in epoch microseconds
        self.open_authorizations = set()
        self.held = defaultdict(int)  # payer user id -> sum of remaining open holds

    def new_id(self, prefix, taken):
        while True:
            self.counter += 1
            candidate = f"{prefix}{self.counter}"
            if candidate not in taken:
                return candidate

    def add_user(self, user):
        self.users[user.id] = user
        self.by_handle[user.handle] = user.id
        self.by_email[user.email] = user.id

    def available(self, user):
        return user.balance - self.held[user.id]

    def close_authorization(self, record, status):
        """Close an open hold: release its remainder and set the terminal status."""
        self.held[record["from_user_id"]] -= record["remaining_amount"]
        record["remaining_amount"] = 0
        record["status"] = status
        self.open_authorizations.discard(record["authorization_id"])

    def sweep_expired(self, now=None):
        """Expire every open hold whose expires_at is at or before now (D-202)."""
        now = now_us() if now is None else now
        for auth_id in [a for a in self.open_authorizations if self.expiry_us[a] <= now]:
            self.close_authorization(self.authorizations[auth_id], "expired")

    def add_authorization(self, record, expiry_us):
        auth_id = record["authorization_id"]
        self.authorizations[auth_id] = record
        self.authorization_log.append(auth_id)
        self.expiry_us[auth_id] = expiry_us
        if record["status"] == "open":
            self.open_authorizations.add(auth_id)
            self.held[record["from_user_id"]] += record["remaining_amount"]

    def user_by_handle(self, handle):
        user_id = self.by_handle.get(handle)
        return self.users[user_id] if user_id is not None else None


class Store:
    """Holds the current State; `lock` guards every read-modify-write of it."""

    def __init__(self, state=None):
        self.lock = threading.Lock()
        self.state = state or State()

    def replace(self, state):
        with self.lock:
            self.state = state
