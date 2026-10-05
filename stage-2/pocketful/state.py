"""Owns the in-memory service state and the single global lock (D-01).

Every handler that reads and then writes state does both inside one
`with store.lock:` block. Reset and import build a complete new State outside
the lock and swap it in under the lock, so a rejected one changes nothing.
"""
import threading
from datetime import datetime, timezone


def now_rfc3339():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
