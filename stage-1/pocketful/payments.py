"""Owns money movement: the single transfer primitive, POST /payments and GET /activity.

`transfer` is the only code that changes balances. Callers hold the store lock
and have already checked funds, so the debit, the credit and the payment record
are one atomic step (R-61) and no balance goes negative (I-02).
"""
from . import fields, idempotency
from .auth import caller
from .errors import ApiError, invalid, not_found
from .state import now_rfc3339

MAX_BALANCE = 2 ** 53


def insufficient():
    return ApiError(409, "insufficient_funds", "balance is below the amount")


def check_credit(receiver, amount):
    if receiver.balance + amount > MAX_BALANCE:
        raise invalid("the receiving balance would exceed 2^53")


def transfer(state, sender, receiver, amount, note, visibility,
             request_id=None, settlement_id=None, created_at=None):
    """Record a payment and move the money. Requires the lock and checked funds."""
    payment_id = state.new_id("p_", state.payments)
    payment = {
        "payment_id": payment_id,
        "from_user_id": sender.id, "from_handle": sender.handle,
        "to_user_id": receiver.id, "to_handle": receiver.handle,
        "amount": amount, "currency": state.currency,
        "note": note, "visibility": visibility,
        "request_id": request_id, "settlement_id": settlement_id,
        "created_at": created_at or now_rfc3339(),
    }
    sender.balance -= amount
    receiver.balance += amount
    state.payments[payment_id] = payment
    state.payment_log.append(payment_id)
    return dict(payment)


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
        raise ApiError(422, "self_payment", "cannot pay yourself")
    if user.balance < amount:
        raise insufficient()
    check_credit(receiver, amount)
    return transfer(state, user, receiver, amount, note, visibility)


def create(store, req, token):
    return idempotency.run(store, req, token, req.json(), _create)


def visible_to(payment, user_id):
    """The feed contract (R-74): public, or the caller is a party."""
    return (payment["visibility"] == "public"
            or user_id in (payment["from_user_id"], payment["to_user_id"]))


def paginate(items, limit, offset):
    """Slice an iterable newest-first list; has_more is true iff items remain."""
    window = []
    has_more = False
    for index, item in enumerate(items):
        if index < offset:
            continue
        if len(window) == limit:
            has_more = True
            break
        window.append(item)
    return window, has_more


def activity(store, req, token):
    limit, offset = fields.page(req.query)
    with store.lock:
        state = store.state
        user = caller(state, token)
        visible = (state.payments[pid] for pid in reversed(state.payment_log)
                   if visible_to(state.payments[pid], user.id))
        window, has_more = paginate(visible, limit, offset)
        return 200, {"payments": [dict(p) for p in window], "has_more": has_more}
