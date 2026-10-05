"""Owns POST /settlements: operator-only atomic net batches (R-92..R-101, spec §11).

Inside one lock acquisition: every entry is validated in input order (D-08,
D-17), then net affordability is checked per wallet against available funds
(R-96, R-208), then all member payments are recorded and the net deltas applied.
Any failure happens before the first write, so nothing commits and the key
stays unclaimed (R-97).
"""
from collections import defaultdict

from . import fields, idempotency
from .errors import ApiError, forbidden, invalid, not_found
from .payments import MAX_BALANCE, insufficient, record_payment
from .state import now_rfc3339

MAX_TRANSFERS = 32


def _authorize(state, user):
    if user.id not in state.operators:
        raise forbidden("settlements require an operator")


def _entry(state, entry):
    if not isinstance(entry, dict):
        raise invalid("each transfer must be an object")
    fields.check_types(entry, {"from_handle": str, "to_handle": str})
    fields.require(entry, "from_handle", "to_handle")
    amount = fields.amount(entry)
    note = fields.note(entry)
    visibility = fields.visibility(entry)
    sender = state.user_by_handle(entry["from_handle"])
    receiver = state.user_by_handle(entry["to_handle"])
    if sender is None or receiver is None:
        raise not_found("no user has that handle")
    if sender.id == receiver.id:
        raise ApiError(422, "self_payment", "a transfer cannot be to the same wallet")
    return sender, receiver, amount, note, visibility


def _create(state, user, body):
    transfers = body.get("transfers")
    if not isinstance(transfers, list) or not 1 <= len(transfers) <= MAX_TRANSFERS:
        raise invalid(f"transfers must be an array of 1..{MAX_TRANSFERS} objects")
    entries = [_entry(state, entry) for entry in transfers]

    deltas = defaultdict(int)
    for sender, receiver, amount, _, _ in entries:
        deltas[sender.id] -= amount
        deltas[receiver.id] += amount
    for user_id, delta in deltas.items():
        balance = state.users[user_id].balance + delta
        if balance - state.held[user_id] < 0:  # held funds cannot fund net debits (R-208)
            raise insufficient()
        if balance > MAX_BALANCE:
            raise invalid("a resulting balance would exceed 2^53")

    settlement_id = state.new_id("st_", state.settlements)
    committed_at = now_rfc3339()
    payments = [record_payment(state, sender, receiver, amount, note, visibility,
                               settlement_id=settlement_id, created_at=committed_at)
                for sender, receiver, amount, note, visibility in entries]
    for user_id, delta in deltas.items():
        state.users[user_id].balance += delta
    response = {"settlement_id": settlement_id, "committed_at": committed_at,
                "payments": payments}
    state.settlements[settlement_id] = response
    return response


def create(store, req, token):
    return idempotency.run(store, req, token, req.json(), _create, authorize=_authorize)
