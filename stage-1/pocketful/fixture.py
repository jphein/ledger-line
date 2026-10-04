"""Owns POST /_test/reset: validating a fixture and building a fresh State from it.

Validation runs completely before anything is hashed or swapped in, so a bad
fixture is 422 and the previous state stays intact (R-18, S-12, S-22).
Seeded records get created_at = reset time; a later array index is newer (D-14).
"""
from . import passwords
from .errors import invalid
from .fields import HANDLE_RE, VISIBILITIES, integral_value
from .state import State, User, now_rfc3339

MINOR_UNITS = (0, 2, 3)
STATUSES = ("pending", "paid", "declined", "cancelled")
MAX_BALANCE = 2 ** 53


def _obj(value, what):
    if not isinstance(value, dict):
        raise invalid(f"{what} must be an object")
    return value


def _list(body, name):
    value = body.get(name, [])
    if not isinstance(value, list):
        raise invalid(f"{name} must be an array")
    return value


def _str(obj, name, what, default=None):
    if name not in obj and default is not None:
        return default
    value = obj.get(name)
    if not isinstance(value, str):
        raise invalid(f"{what}.{name} must be a string")
    return value


def _id(obj, name, what):
    value = _str(obj, name, what)
    if not 1 <= len(value) <= 64:
        raise invalid(f"{what}.{name} must be 1..64 characters")
    return value


def _int(obj, name, what, minimum, maximum):
    value = integral_value(obj.get(name))
    if value is None or not minimum <= value <= maximum:
        raise invalid(f"{what}.{name} must be an integer in {minimum}..{maximum}")
    return value


def _user_ref(obj, name, what, users):
    value = _id(obj, name, what)
    if value not in users:
        raise invalid(f"{what}.{name} references an unknown user")
    return users[value]


def parse_fixture(body):
    """Validate a fixture; return (state without password hashes, passwords in user order)."""
    currency = _str(body, "currency", "fixture")
    if not currency:
        raise invalid("currency must be non-empty")
    minor_units = integral_value(body.get("minor_units"))
    if minor_units not in MINOR_UNITS:
        raise invalid("minor_units must be 0, 2 or 3")
    if "users" not in body:
        raise invalid("users is required")

    state = State(currency, minor_units)
    secrets = []
    for raw in _list(body, "users"):
        u = _obj(raw, "user")
        user = User(id=_id(u, "id", "user"), email=_str(u, "email", "user"),
                    handle=_str(u, "handle", "user"),
                    display_name=_str(u, "display_name", "user"), pw_hash=None,
                    balance=_int(u, "balance", "user", 0, MAX_BALANCE))
        secrets.append(_str(u, "password", "user"))
        if not HANDLE_RE.fullmatch(user.handle):
            raise invalid("user.handle must match ^[a-z0-9_]{1,20}$")
        if user.id in state.users or user.handle in state.by_handle or user.email in state.by_email:
            raise invalid("duplicate user id, handle or email")
        state.add_user(user)

    created_at = now_rfc3339()
    for raw in _list(body, "payments"):
        p = _obj(raw, "payment")
        pid = _id(p, "id", "payment")
        if pid in state.payments:
            raise invalid("duplicate payment id")
        sender = _user_ref(p, "from_user_id", "payment", state.users)
        receiver = _user_ref(p, "to_user_id", "payment", state.users)
        visibility = _str(p, "visibility", "payment", "public")
        if visibility not in VISIBILITIES:
            raise invalid("payment.visibility must be public or private")
        state.payments[pid] = {
            "payment_id": pid,
            "from_user_id": sender.id, "from_handle": sender.handle,
            "to_user_id": receiver.id, "to_handle": receiver.handle,
            "amount": _int(p, "amount", "payment", 0, MAX_BALANCE),
            "currency": currency,
            "note": _str(p, "note", "payment", ""),
            "visibility": visibility,
            "request_id": None, "settlement_id": None,
            "created_at": created_at,
        }
        state.payment_log.append(pid)

    for raw in _list(body, "requests"):
        r = _obj(raw, "request")
        rid = _id(r, "id", "request")
        if rid in state.requests:
            raise invalid("duplicate request id")
        requester = _user_ref(r, "requester_id", "request", state.users)
        payer = _user_ref(r, "payer_id", "request", state.users)
        status = _str(r, "status", "request", "pending")
        if status not in STATUSES:
            raise invalid("request.status is not a known status")
        payment_id = r.get("payment_id")
        if payment_id is not None and not isinstance(payment_id, str):
            raise invalid("request.payment_id must be a string or null")
        state.requests[rid] = {
            "request_id": rid,
            "requester_id": requester.id, "requester_handle": requester.handle,
            "payer_id": payer.id, "payer_handle": payer.handle,
            "amount": _int(r, "amount", "request", 0, MAX_BALANCE),
            "currency": currency,
            "note": _str(r, "note", "request", ""),
            "status": status,
            "payment_id": payment_id,
            "created_at": created_at,
        }
        state.request_log.append(rid)

    for raw in _list(body, "settlement_operator_ids"):
        if not isinstance(raw, str) or raw not in state.users:
            raise invalid("settlement_operator_ids must list known user ids")
        state.operators.add(raw)
    return state, secrets


def build_state(body):
    """Validate, then hash every seeded password (outside any lock)."""
    state, secrets = parse_fixture(body)
    for user, pw_hash in zip(state.users.values(), passwords.hash_many(secrets)):
        user.pw_hash = pw_hash
    return state
