"""Owns holds: POST /authorizations, capture, void and GET /authorizations (R-203..R-230).

A hold reserves money without moving it: `state.held[payer]` rises by the
amount and `available = total - held` falls. Every operation runs under the
store lock after `caller()` has swept expired holds (D-202), so create, capture,
void and expiry are serialised (R-234) and `available` never goes negative.
"""
from datetime import datetime, timedelta, timezone

from . import fields, idempotency
from .auth import caller
from .errors import ApiError, forbidden, invalid, malformed, not_found
from .fields import integral_value
from .payments import check_credit, insufficient, paginate, transfer
from .state import now_us, parse_rfc3339_us

STATUSES = ("open", "captured", "voided", "expired")
DIRECTIONS = ("incoming", "outgoing")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_LAST = datetime(9999, 12, 31, tzinfo=timezone.utc)


def _not_open():
    return ApiError(409, "authorization_not_open", "authorization is not open")


def _rfc3339_ms(moment):
    return moment.isoformat(timespec="milliseconds")


def _create(state, user, body):
    fields.check_types(body, {"to_handle": str})
    fields.require(body, "to_handle")
    amount = fields.amount(body)
    note = fields.note(body)
    visibility = fields.visibility(body)
    receiver = state.user_by_handle(body["to_handle"])
    if receiver is None:
        raise not_found("no user has that handle")
    if receiver.id == user.id:
        raise ApiError(422, "self_payment", "cannot authorize a payment to yourself")
    if state.available(user) < amount:
        raise insufficient()
    created = _EPOCH + timedelta(milliseconds=now_us() // 1000)
    # Any positive ttl is valid; expiry is clamped to the last representable day.
    # Integer comparison first: no float rounding, and no timedelta overflow.
    limit = (_LAST - created) // timedelta(seconds=1)
    expires = _LAST if state.ttl_seconds >= limit else created + timedelta(seconds=state.ttl_seconds)
    auth_id = state.new_id("a_", state.authorizations)
    record = {
        "authorization_id": auth_id,
        "from_user_id": user.id, "from_handle": user.handle,
        "to_user_id": receiver.id, "to_handle": receiver.handle,
        "amount": amount, "captured_amount": 0, "remaining_amount": amount,
        "payment_ids": [], "currency": state.currency,
        "note": note, "visibility": visibility, "status": "open",
        "expires_at": _rfc3339_ms(expires), "payment_id": None,
        "created_at": _rfc3339_ms(created),
    }
    state.add_authorization(record, parse_rfc3339_us(record["expires_at"]))
    return view(record)


def view(record):
    return dict(record, payment_ids=list(record["payment_ids"]))


def create(store, req, token):
    return idempotency.run(store, req, token, req.json(), _create)


def _find(state, auth_id):
    record = state.authorizations.get(auth_id)
    if record is None:
        raise not_found("no such authorization")
    return record


def _capture_fields(body):
    """D-203 field rules: amount integral and >= 1 (422); final boolean (400)."""
    amount = None
    if "amount" in body:
        amount = integral_value(body["amount"])
        if amount is None or amount < 1:
            raise invalid("amount must be an integer of at least 1")
    final = body.get("final", True)
    if not isinstance(final, bool):
        raise malformed("final must be a boolean")
    return amount, final


def capture(store, req, token):
    auth_id = req.params[0]

    def effect(state, user, body):
        amount, final = _capture_fields(body)
        record = _find(state, auth_id)
        if record["to_user_id"] != user.id:
            raise forbidden("only the receiver may capture")
        if record["status"] == "expired":
            raise ApiError(409, "authorization_expired", "authorization has expired")
        if record["status"] != "open":
            raise _not_open()
        remaining = record["remaining_amount"]
        if amount is None:
            amount = remaining
        if amount > remaining:
            raise ApiError(422, "capture_exceeds_authorization",
                           "amount exceeds the remaining authorized amount")
        payer = state.users[record["from_user_id"]]
        check_credit(user, amount)
        # Captures spend the reserved money: release that part of the hold, then move it.
        state.held[payer.id] -= amount
        record["remaining_amount"] = remaining - amount
        payment = transfer(state, payer, user, amount, record["note"], record["visibility"],
                           authorization_id=auth_id)
        record["captured_amount"] += amount
        record["payment_id"] = payment["payment_id"]
        record["payment_ids"].append(payment["payment_id"])
        if final or record["remaining_amount"] == 0:
            state.close_authorization(record, "captured")
        return payment

    return idempotency.run(store, req, token, req.json(empty_as_object=True), effect)


def void(store, req, token):
    """Payer only, no key, body ignored (D-204): 404, 403, voided 200, closed 409."""
    with store.lock:
        state = store.state
        user = caller(state, token)
        record = _find(state, req.params[0])
        if record["from_user_id"] != user.id:
            raise forbidden("only the payer may void")
        if record["status"] in ("captured", "expired"):
            raise _not_open()
        if record["status"] == "open":
            state.close_authorization(record, "voided")
        return 200, view(record)


def _choice(query, name, allowed):
    value = query.get(name)
    if value is not None and value not in allowed:
        raise invalid(f"{name} must be one of {', '.join(allowed)}")
    return value


def list_authorizations(store, req, token):
    direction = _choice(req.query, "direction", DIRECTIONS)
    status = _choice(req.query, "status", STATUSES)
    limit, offset = fields.page(req.query)
    with store.lock:
        state = store.state
        user = caller(state, token)
        roles = {"outgoing": ("from_user_id",), "incoming": ("to_user_id",),
                 None: ("from_user_id", "to_user_id")}[direction]

        def wanted(record):
            return (any(record[role] == user.id for role in roles)
                    and (status is None or record["status"] == status))

        matches = (state.authorizations[a] for a in reversed(state.authorization_log)
                   if wanted(state.authorizations[a]))
        window, has_more = paginate(matches, limit, offset)
        return 200, {"authorizations": [view(r) for r in window], "has_more": has_more}
