"""Owns signup, login, bearer-token resolution and GET /me (spec §6, R-31..R-40).

Password work happens outside the lock; the uniqueness checks and the write
happen together inside it, so concurrent signups cannot both take an email or handle.
"""
import re
import secrets

from . import passwords
from .errors import ApiError, invalid, unauthenticated
from .fields import check_types, require
from .state import User

MIN_PASSWORD = 8
_NON_HANDLE = re.compile(r"[^a-z0-9_]")


def derive_handle(email):
    """Local part, lowercased, non-[a-z0-9_] -> "_", truncated to 20 (R-14)."""
    local = email.rsplit("@", 1)[0]
    return _NON_HANDLE.sub("_", local.lower())[:20]


def _valid_email(email):
    local, sep, domain = email.rpartition("@")
    return bool(sep and local and domain and "@" not in local
                and not any(ch.isspace() for ch in email))


def bearer_token(store, headers):
    """Return the caller's bearer token if it is known, else raise 401 (R-24).

    Handlers re-resolve the token with `caller` inside their own lock, so a
    reset between the two steps can never bind a stale token to a new user.
    """
    header = headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise unauthenticated("missing or malformed bearer token")
    with store.lock:
        known = token in store.state.tokens
    if not known:
        raise unauthenticated("unknown bearer token")
    return token


def caller(state, token):
    """The User behind a token in this state (call with the lock held)."""
    user = state.users.get(state.tokens.get(token))
    if user is None:
        raise unauthenticated("unknown bearer token")
    return user


def _issue(state, user):
    token = secrets.token_urlsafe(32)
    state.tokens[token] = user.id
    return {"user_id": user.id, "display_name": user.display_name, "token": token}


def _check_unique(state, email, handle):
    if email in state.by_email:
        raise ApiError(409, "email_taken", "email already registered")
    if handle in state.by_handle:
        raise ApiError(409, "handle_taken", "derived handle already taken")


def signup(store, body):
    check_types(body, {"email": str, "password": str, "display_name": str})
    require(body, "email", "password", "display_name")
    email, password = body["email"], body["password"]
    if not _valid_email(email):
        raise invalid("email must be of the form local@domain")
    if len(password) < MIN_PASSWORD:
        raise invalid(f"password must be at least {MIN_PASSWORD} characters")
    handle = derive_handle(email)
    with store.lock:
        _check_unique(store.state, email, handle)
    pw_hash = passwords.hash_password(password)
    with store.lock:
        state = store.state
        _check_unique(state, email, handle)
        user = User(id=state.new_id("u_", state.users), email=email, handle=handle,
                    display_name=body["display_name"], pw_hash=pw_hash, balance=0)
        state.add_user(user)
        return 201, _issue(state, user)


def login(store, body):
    check_types(body, {"email": str, "password": str})
    require(body, "email", "password")
    email = body["email"]
    with store.lock:
        user_id = store.state.by_email.get(email)
        pw_hash = store.state.users[user_id].pw_hash if user_id is not None else None
    if pw_hash is None or not passwords.verify_password(body["password"], pw_hash):
        raise unauthenticated("wrong email or password")
    with store.lock:
        state = store.state
        user = state.users.get(state.by_email.get(email))
        if user is None or user.pw_hash != pw_hash:
            raise unauthenticated("wrong email or password")
        return 200, _issue(state, user)


def me(store, token):
    with store.lock:
        state = store.state
        user = caller(state, token)
        return 200, {"user_id": user.id, "display_name": user.display_name,
                     "handle": user.handle, "balance": user.balance,
                     "currency": state.currency, "minor_units": state.minor_units}
