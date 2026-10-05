"""Owns POST /splits and the equal-split rule (R-76..R-83, spec §9).

A split checks no balances; it only creates pending requests, one per
participant other than the caller, inside one lock acquisition.
"""
from . import fields, idempotency
from .errors import invalid, malformed, not_found
from .money_requests import new_request
from .state import now_rfc3339


def equal_shares(amount, count):
    """Whole units summing to amount, differing by at most one; extras go first."""
    base, extra = divmod(amount, count)
    return [base + 1 if index < extra else base for index in range(count)]


def _create(state, user, body):
    fields.check_types(body, {"participant_handles": list})
    fields.require(body, "participant_handles")
    handles = body["participant_handles"]
    if not all(isinstance(handle, str) for handle in handles):
        raise malformed("participant_handles must contain strings")
    amount = fields.amount(body)
    note = fields.note(body)
    if not handles:
        raise invalid("participant_handles must not be empty")
    if len(set(handles)) != len(handles):
        raise invalid("participant_handles must not contain duplicates")
    participants = []
    for handle in handles:
        participant = state.user_by_handle(handle)
        if participant is None:
            raise not_found(f"no user has handle {handle!r}")
        participants.append(participant)

    created_at = now_rfc3339()
    shares = equal_shares(amount, len(participants))
    requests = [new_request(state, user, participant, share, note, created_at)
                for participant, share in zip(participants, shares)
                if participant.id != user.id]
    split_id = state.new_id("sp_", state.splits)
    response = {
        "split_id": split_id, "amount": amount, "currency": state.currency, "note": note,
        "shares": [{"handle": h, "amount": s} for h, s in zip(handles, shares)],
        "requests": requests, "created_at": created_at,
    }
    state.splits[split_id] = response
    return response


def create(store, req, token):
    return idempotency.run(store, req, token, req.json(), _create)
