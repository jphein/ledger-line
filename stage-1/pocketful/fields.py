"""Owns field and query-parameter validation shared by every endpoint (spec §5)."""
import re
from decimal import Decimal

from .errors import ApiError, invalid, malformed

MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
MAX_KEY = 255
VISIBILITIES = ("public", "private")
HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
_DIGITS_RE = re.compile(r"[0-9]+")
_MISSING = object()


def integral_value(value):
    """Return value as an int if it is a JSON number with an integral value, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite() or value.adjusted() > 30:
            return None
        if value != value.to_integral_value():
            return None
        return int(value)
    return None


def amount(body, name="amount", minimum=1):
    """Required amount: integral, minimum..MAX_AMOUNT; every failure is 422 (R-27)."""
    if name not in body:
        raise invalid(f"{name} is required")
    value = integral_value(body[name])
    if value is None:
        raise invalid(f"{name} must be an integer")
    if value < minimum or value > MAX_AMOUNT:
        raise invalid(f"{name} must be between {minimum} and {MAX_AMOUNT}")
    return value


def note(body):
    """Optional note, default "", verbatim; non-string (incl. null) is 422 (R-27)."""
    if "note" not in body:
        return ""
    value = body["note"]
    if not isinstance(value, str):
        raise invalid("note must be a string")
    if len(value) > MAX_NOTE:
        raise invalid(f"note must be at most {MAX_NOTE} characters")
    return value


def visibility(body):
    """Optional visibility, default "public"; anything else (incl. null) is 422."""
    if "visibility" not in body:
        return "public"
    value = body["visibility"]
    if value not in VISIBILITIES or not isinstance(value, str):
        raise invalid("visibility must be public or private")
    return value


def check_types(body, spec):
    """Wrong JSON type on a present field is 400 (D-03). spec: {name: type}."""
    for name, kind in spec.items():
        if name in body and not isinstance(body[name], kind):
            raise malformed(f"{name} has the wrong type")


def require(body, *names):
    """A missing required field is 422 (D-03)."""
    for name in names:
        if name not in body:
            raise invalid(f"{name} is required")


def query_int(query, name, default, minimum, maximum=None):
    """Integer query parameter: plain decimal digits only, else 422 (R-28)."""
    raw = query.get(name)
    if raw is None:
        return default
    if not _DIGITS_RE.fullmatch(raw):
        raise invalid(f"{name} must be a non-negative decimal integer")
    digits = raw.lstrip("0") or "0"
    value = int(digits) if len(digits) <= 18 else 10 ** 18
    if value < minimum or (maximum is not None and value > maximum):
        raise invalid(f"{name} is out of range")
    return value


def page(query):
    """limit 1..200 (default 50), offset >= 0 (default 0)."""
    limit = query_int(query, "limit", 50, 1, 200)
    offset = query_int(query, "offset", 0, 0)
    return limit, offset


def idempotency_key(headers):
    """Idempotency-Key: absent/empty is 400, over 255 characters is 422 (R-23, R-29)."""
    key = headers.get("Idempotency-Key")
    if key is None or key == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    if len(key) > MAX_KEY:
        raise invalid(f"Idempotency-Key must be at most {MAX_KEY} characters")
    return key
