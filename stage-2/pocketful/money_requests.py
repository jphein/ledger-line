"""Owns payment requests: create, pay, decline, cancel and GET /requests (R-63..R-75).

Every status change reads and writes the request under the store lock, so a
request leaves `pending` exactly once (I-03, I-06). Check order is D-04:
unknown id 404, then role 403, then status 409, then funds 409.
"""
from . import fields, idempotency
from .auth import caller
from .errors import ApiError, forbidden, invalid, not_found
from .payments import check_credit, insufficient, paginate, transfer
from .state import now_rfc3339

STATUSES = ("pending", "paid", "declined", "cancelled")
DIRECTIONS = ("incoming", "outgoing")


def not_pending():
    return ApiError(409, "request_not_pending", "request is not pending")


def new_request(state, requester, payer, amount, note, created_at=None):
    """Record a pending request (requires the lock); returns its response body."""
    request_id = state.new_id("rq_", state.requests)
    record = {
        "request_id": request_id,
        "requester_id": requester.id, "requester_handle": requester.handle,
        "payer_id": payer.id, "payer_handle": payer.handle,
        "amount": amount, "currency": state.currency, "note": note,
        "status": "pending", "payment_id": None,
        "created_at": created_at or now_rfc3339(),
    }
    state.requests[request_id] = record
    state.request_log.append(request_id)
    return dict(record)


def _create(state, user, body):
    fields.check_types(body, {"payer_handle": str})
    fields.require(body, "payer_handle")
    amount = fields.amount(body)
    note = fields.note(body)
    payer = state.user_by_handle(body["payer_handle"])
    if payer is None:
        raise not_found("no user has that handle")
    if payer.id == user.id:
        raise ApiError(422, "self_request", "cannot request money from yourself")
    return new_request(state, user, payer, amount, note)


def create(store, req, token):
    return idempotency.run(store, req, token, req.json(), _create)


def _find(state, request_id):
    record = state.requests.get(request_id)
    if record is None:
        raise not_found("no such request")
    return record


def pay(store, req, token):
    request_id = req.params[0]

    def effect(state, user, body):
        visibility = fields.visibility(body)
        record = _find(state, request_id)
        if record["payer_id"] != user.id:
            raise forbidden("only the payer may pay this request")
        if record["status"] != "pending":
            raise not_pending()
        amount = record["amount"]
        if state.available(user) < amount:
            raise insufficient()
        receiver = state.users[record["requester_id"]]
        check_credit(receiver, amount)
        payment = transfer(state, user, receiver, amount, record["note"], visibility,
                           request_id=request_id)
        record["status"] = "paid"
        record["payment_id"] = payment["payment_id"]
        return payment

    return idempotency.run(store, req, token, req.json(empty_as_object=True), effect)


def _transition(store, req, token, role, target):
    """Decline/cancel: no key, body ignored (D-15); repeating the same target is 200."""
    with store.lock:
        state = store.state
        user = caller(state, token)
        record = _find(state, req.params[0])
        if record[role] != user.id:
            raise forbidden(f"only the {role.removesuffix('_id')} may do this")
        if record["status"] != target:
            if record["status"] != "pending":
                raise not_pending()
            record["status"] = target
        return 200, dict(record)


def decline(store, req, token):
    return _transition(store, req, token, "payer_id", "declined")


def cancel(store, req, token):
    return _transition(store, req, token, "requester_id", "cancelled")


def _choice(query, name, allowed):
    value = query.get(name)
    if value is not None and value not in allowed:
        raise invalid(f"{name} must be one of {', '.join(allowed)}")
    return value


def list_requests(store, req, token):
    direction = _choice(req.query, "direction", DIRECTIONS)
    status = _choice(req.query, "status", STATUSES)
    limit, offset = fields.page(req.query)
    with store.lock:
        state = store.state
        user = caller(state, token)
        roles = {"incoming": ("payer_id",), "outgoing": ("requester_id",),
                 None: ("payer_id", "requester_id")}[direction]

        def wanted(record):
            return (any(record[role] == user.id for role in roles)
                    and (status is None or record["status"] == status))

        matches = (state.requests[rid] for rid in reversed(state.request_log)
                   if wanted(state.requests[rid]))
        window, has_more = paginate(matches, limit, offset)
        return 200, {"requests": [dict(r) for r in window], "has_more": has_more}
