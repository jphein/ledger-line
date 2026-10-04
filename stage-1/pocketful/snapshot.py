"""Owns GET /_test/export and POST /_test/import (R-84..R-91, spec §10).

Export serialises the whole State under the lock into fresh plain JSON values,
so later writes cannot change it (R-88). Import validates the entire document
and builds a new State outside the lock, then swaps it in; an invalid document
is 422 and leaves the destination untouched (R-87, S-17). Nothing is replayed:
balances, ids, timestamps, tokens and idempotency records are restored as-is.
"""
import copy
from decimal import Decimal

from . import passwords
from .errors import invalid
from .fields import HANDLE_RE, VISIBILITIES, integral_value
from .fixture import MAX_BALANCE, MINOR_UNITS, STATUSES
from .state import State, User

TRACK, FORMAT_VERSION = "pocketful", 1

PAYMENT_FIELDS = ("payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                  "amount", "currency", "note", "visibility", "request_id",
                  "settlement_id", "created_at")
REQUEST_FIELDS = ("request_id", "requester_id", "requester_handle", "payer_id",
                  "payer_handle", "amount", "currency", "note", "status", "payment_id",
                  "created_at")


def export_state(store):
    with store.lock:
        s = store.state
        state = {
            "currency": s.currency, "minor_units": s.minor_units, "counter": s.counter,
            "users": [{"id": u.id, "email": u.email, "handle": u.handle,
                       "display_name": u.display_name, "pw_hash": u.pw_hash,
                       "balance": u.balance} for u in s.users.values()],
            "tokens": dict(s.tokens),
            "operators": sorted(s.operators),
            "payments": [dict(s.payments[pid]) for pid in s.payment_log],
            "requests": [dict(s.requests[rid]) for rid in s.request_log],
            "splits": copy.deepcopy(list(s.splits.values())),
            "settlements": copy.deepcopy(list(s.settlements.values())),
            "idempotency": [{"user_id": k[0], "method": k[1], "path": k[2], "key": k[3],
                             "body": canon, "response": copy.deepcopy(response)}
                            for k, (canon, response) in s.idempotency.items()],
        }
    return {"track": TRACK, "format_version": FORMAT_VERSION, "state": state}


# --- import validation -------------------------------------------------------

def _get(obj, name, kind, nullable=False):
    if not isinstance(obj, dict) or name not in obj:
        raise invalid(f"state is missing {name}")
    value = obj[name]
    if value is None and nullable:
        return None
    if kind is int:
        value = integral_value(value)
        if value is None:
            raise invalid(f"{name} must be an integer")
        return value
    if not isinstance(value, kind):
        raise invalid(f"{name} has the wrong type")
    return value


def _plain(value):
    """Opaque stored JSON (responses): integral numbers become ints; others are invalid."""
    if isinstance(value, Decimal):
        number = integral_value(value)
        if number is None:
            raise invalid("state contains a non-integral number")
        return number
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _unique(table, key, what):
    if key in table:
        raise invalid(f"duplicate {what} {key!r}")


def _known_user(value, users, what):
    if not isinstance(value, str) or value not in users:
        raise invalid(f"{what} references an unknown user")
    return value


def _record(raw, names, nullable, users, user_fields):
    """Validate a payment/request record: exact field set, typed, users known."""
    record = {}
    for name in names:
        if name == "amount":
            record[name] = _get(raw, name, int)
            if not 0 <= record[name] <= MAX_BALANCE:
                raise invalid("amount out of range")
        else:
            record[name] = _get(raw, name, str, nullable=name in nullable)
    for name in user_fields:
        _known_user(record[name], users, name)
    return record


def build_state(doc):
    """Validate an export document and return a new State (no lock needed)."""
    if _get(doc, "track", str) != TRACK or _get(doc, "format_version", int) != FORMAT_VERSION:
        raise invalid("unsupported track or format_version")
    raw = _get(doc, "state", dict)

    minor_units = _get(raw, "minor_units", int)
    if minor_units not in MINOR_UNITS:
        raise invalid("minor_units must be 0, 2 or 3")
    state = State(_get(raw, "currency", str), minor_units)
    state.counter = _get(raw, "counter", int)
    if state.counter < 0:
        raise invalid("counter must be non-negative")

    for u in _get(raw, "users", list):
        user = User(id=_get(u, "id", str), email=_get(u, "email", str),
                    handle=_get(u, "handle", str), display_name=_get(u, "display_name", str),
                    pw_hash=_get(u, "pw_hash", str), balance=_get(u, "balance", int))
        if not HANDLE_RE.fullmatch(user.handle) or not 0 <= user.balance <= MAX_BALANCE:
            raise invalid("invalid user handle or balance")
        if not passwords.is_valid_hash(user.pw_hash):
            raise invalid("invalid password hash")
        _unique(state.users, user.id, "user id")
        _unique(state.by_handle, user.handle, "handle")
        _unique(state.by_email, user.email, "email")
        state.add_user(user)

    for token, user_id in _get(raw, "tokens", dict).items():
        state.tokens[token] = _known_user(user_id, state.users, "token")

    for user_id in _get(raw, "operators", list):
        state.operators.add(_known_user(user_id, state.users, "operator"))

    for p in _get(raw, "payments", list):
        record = _record(p, PAYMENT_FIELDS, ("request_id", "settlement_id"), state.users, ("from_user_id", "to_user_id"))
        if record["visibility"] not in VISIBILITIES:
            raise invalid("invalid payment visibility")
        _unique(state.payments, record["payment_id"], "payment id")
        state.payments[record["payment_id"]] = record
        state.payment_log.append(record["payment_id"])

    for r in _get(raw, "requests", list):
        record = _record(r, REQUEST_FIELDS, ("payment_id",), state.users, ("requester_id", "payer_id"))
        if record["status"] not in STATUSES:
            raise invalid("invalid request status")
        _unique(state.requests, record["request_id"], "request id")
        state.requests[record["request_id"]] = record
        state.request_log.append(record["request_id"])

    for kind, table, id_name in (("splits", state.splits, "split_id"),
                                 ("settlements", state.settlements, "settlement_id")):
        for item in _get(raw, kind, list):
            item_id = _get(item, id_name, str)
            _unique(table, item_id, id_name)
            table[item_id] = _plain(item)

    for rec in _get(raw, "idempotency", list):
        user_id = _known_user(_get(rec, "user_id", str), state.users, "idempotency record")
        key = (user_id, _get(rec, "method", str), _get(rec, "path", str), _get(rec, "key", str))
        state.idempotency[key] = (_get(rec, "body", str), _plain(_get(rec, "response", dict)))
    return state


def import_state(store, doc):
    store.replace(build_state(doc))
