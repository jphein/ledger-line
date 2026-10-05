"""Owns routing: the route table, authentication order and error rendering.

`dispatch` is transport-free (it takes a Request and returns status + body), so
the HTTP server and the unit tests drive exactly the same code.
"""
import re
import sys
import traceback

from . import (auth, authorizations, fixture, money_requests, payments, settlements, snapshot,
               splits)
from .errors import ApiError, not_found
from .jsonio import parse_body


class Request:
    def __init__(self, method, path, query=None, headers=None, raw=b""):
        self.method = method
        self.path = path
        self.query = query or {}
        self.headers = headers or {}
        self.raw = raw

    def json(self, empty_as_object=False):
        """The body as a JSON object; 400 otherwise (R-22)."""
        if empty_as_object and not self.raw.strip():
            return {}
        return parse_body(self.raw)


def _health(store, req, token):
    return 200, {"status": "ok"}


def _reset(store, req, token):
    store.replace(fixture.build_state(req.json()))
    return 204, None


def _export(store, req, token):
    return 200, snapshot.export_state(store)


def _import(store, req, token):
    snapshot.import_state(store, req.json())
    return 204, None


def _signup(store, req, token):
    return auth.signup(store, req.json())


def _login(store, req, token):
    return auth.login(store, req.json())


def _me(store, req, token):
    return auth.me(store, token)


PUBLIC, AUTHED = False, True

# (method, path regex, handler, needs bearer token). Path groups become req.params.
ROUTES = [
    ("GET", r"/health", _health, PUBLIC),
    ("POST", r"/_test/reset", _reset, PUBLIC),
    ("GET", r"/_test/export", _export, PUBLIC),
    ("POST", r"/_test/import", _import, PUBLIC),
    ("POST", r"/auth/signup", _signup, PUBLIC),
    ("POST", r"/auth/login", _login, PUBLIC),
    ("GET", r"/me", _me, AUTHED),
    ("POST", r"/payments", payments.create, AUTHED),
    ("GET", r"/activity", payments.activity, AUTHED),
    ("POST", r"/requests", money_requests.create, AUTHED),
    ("GET", r"/requests", money_requests.list_requests, AUTHED),
    ("POST", r"/requests/([^/]+)/pay", money_requests.pay, AUTHED),
    ("POST", r"/requests/([^/]+)/decline", money_requests.decline, AUTHED),
    ("POST", r"/requests/([^/]+)/cancel", money_requests.cancel, AUTHED),
    ("POST", r"/splits", splits.create, AUTHED),
    ("POST", r"/settlements", settlements.create, AUTHED),
    ("POST", r"/authorizations", authorizations.create, AUTHED),
    ("GET", r"/authorizations", authorizations.list_authorizations, AUTHED),
    ("POST", r"/authorizations/([^/]+)/capture", authorizations.capture, AUTHED),
    ("POST", r"/authorizations/([^/]+)/void", authorizations.void, AUTHED),
]


def _match(method, path):
    path_known = False
    for route_method, pattern, handler, needs_auth in ROUTES:
        found = re.fullmatch(pattern, path)
        if found:
            path_known = True
            if route_method == method:
                return handler, needs_auth, found.groups()
    raise not_found("no such endpoint" if not path_known else "method not supported")


def dispatch(store, req):
    """Return (status, body-or-None) for one request; never raises."""
    try:
        handler, needs_auth, params = _match(req.method, req.path)
        req.params = params
        token = auth.bearer_token(store, req.headers) if needs_auth else None
        return handler(store, req, token)
    except ApiError as err:
        return err.status, err.body()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 500, {"error": {"code": "internal_error", "message": "internal error"}}
