"""Owns the idempotent write path (spec §7, R-41..R-51, D-02, D-10, D-11).

The whole sequence (claimed-key lookup, validation, resource checks, effect,
record) runs inside one lock acquisition, so concurrent identical requests see
exactly one first use and the effect happens once (R-49). Effects validate
before mutating, so a 4xx records nothing and the key stays free (R-47).
"""
import copy

from .auth import caller
from .errors import ApiError
from .fields import idempotency_key
from .jsonio import canonical


def run(store, req, token, body, effect, authorize=None):
    """Execute `effect(state, user, body) -> response` at most once per key.

    `authorize(state, user)` runs before the key header is read (settlements' 403).
    Returns (201, response) on first use and (200, original response) on replay.
    """
    canon = canonical(body)
    with store.lock:
        state = store.state
        user = caller(state, token)
        if authorize:
            authorize(state, user)
        record_key = (user.id, req.method, req.path, idempotency_key(req.headers))
        record = state.idempotency.get(record_key)
        if record is not None:
            if record[0] != canon:
                raise ApiError(409, "idempotency_key_reuse",
                               "key already used with a different body")
            return 200, copy.deepcopy(record[1])
        response = effect(state, user, body)
        state.idempotency[record_key] = (canon, copy.deepcopy(response))
        return 201, response
