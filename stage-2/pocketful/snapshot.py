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
from .fixture import AUTH_STATUSES, MAX_BALANCE, MAX_TTL_SECONDS, MINOR_UNITS, STATUSES
from .state import State, User, parse_rfc3339_us

TRACK, FORMAT_VERSION = "pocketful", 1

PAYMENT_FIELDS = ("payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                  "amount", "currency", "note", "visibility", "request_id",
                  "settlement_id", "created_at")
AUTH_FIELDS = ("authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
               "amount", "captured_amount", "remaining_amount", "currency", "note",
               "visibility", "status", "expires_at", "payment_id", "created_at")
REQUEST_FIELDS = ("request_id", "requester_id", "requester_handle", "payer_id",
                  "payer_handle", "amount", "currency", "note", "status", "payment_id",
                  "created_at")


def export_state(store):
    with store.lock:
        s = store.state
        s.sweep_expired()
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
            "authorization_ttl_seconds": s.ttl_seconds,
            "authorizations": [dict(s.authorizations[a], payment_ids=list(
                s.authorizations[a]["payment_ids"])) for a in s.authorization_log],
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
        if name in ("amount", "captured_amount", "remaining_amount"):
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
        record = _record(p, PAYMENT_FIELDS, ("request_id", "settlement_id"), state.users,
                         ("from_user_id", "to_user_id"))
        # Stage-1 exports have no authorization_id; it reads as null (D-207, D-211).
        record["authorization_id"] = (_get(p, "authorization_id", str, nullable=True)
                                      if "authorization_id" in p else None)
        if record["visibility"] not in VISIBILITIES:
            raise invalid("invalid payment visibility")
        _unique(state.payments, record["payment_id"], "payment id")
        state.payments[record["payment_id"]] = record
        state.payment_log.append(record["payment_id"])

    for r in _get(raw, "requests", list):
        record = _record(r, REQUEST_FIELDS, ("payment_id",), state.users,
                         ("requester_id", "payer_id"))
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

    # Stage-2 additions; a stage-1 export has neither and gets the defaults (D-207).
    if "authorization_ttl_seconds" in raw:
        state.ttl_seconds = _get(raw, "authorization_ttl_seconds", int)
        if not 1 <= state.ttl_seconds <= MAX_TTL_SECONDS:
            raise invalid("authorization_ttl_seconds out of range")
    for a in _get(raw, "authorizations", list) if "authorizations" in raw else []:
        record, expiry = _authorization(a, state.users)
        _unique(state.authorizations, record["authorization_id"], "authorization id")
        state.add_authorization(record, expiry)
    for user in state.users.values():
        if state.held[user.id] > user.balance:
            raise invalid("open holds exceed a user's balance")
    return state


def _authorization(a, users):
    record = _record(a, AUTH_FIELDS, ("payment_id",), users, ("from_user_id", "to_user_id"))
    ids = _get(a, "payment_ids", list)
    if not all(isinstance(i, str) for i in ids):
        raise invalid("payment_ids must be strings")
    record["payment_ids"] = list(ids)
    amount, captured, remaining = (record["amount"], record["captured_amount"],
                                   record["remaining_amount"])
    if (record["status"] not in AUTH_STATUSES or record["visibility"] not in VISIBILITIES
            or captured + remaining > amount
            or (record["status"] != "open" and remaining != 0)):
        raise invalid("inconsistent authorization")
    try:
        expiry = parse_rfc3339_us(record["expires_at"])
    except (ValueError, OverflowError):
        raise invalid("authorization expires_at is not RFC 3339")
    return record, expiry


def import_state(store, doc):
    try:
        state = build_state(doc)
    except RecursionError:
        raise invalid("state is nested too deeply")
    store.replace(state)
