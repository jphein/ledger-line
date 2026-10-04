"""Owns JSON at the boundary: strict parsing, response encoding, canonical body form.

Floats parse as Decimal so `1e3`, `1000.0` and huge exponents stay exact and never
become inf. The canonical form drives replay comparison (D-11): type-aware and
recursive, so a bool never equals a number while `1000` equals `1000.0`.
"""
import json
from decimal import Decimal, InvalidOperation

from .errors import malformed

# Integers at or beyond this magnitude are canonicalised via Decimal so that
# a long integer literal and the same value in exponent form compare equal
# without ever materialising a giant Python int from an exponent.
_BIG = 10 ** 30


def _reject_constant(name):
    raise ValueError(f"non-JSON constant {name}")


def parse_body(raw):
    """Parse request bytes into a JSON object (dict); anything else is 400."""
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, parse_float=Decimal,
                           parse_constant=_reject_constant)
    except (ValueError, RecursionError, InvalidOperation, ArithmeticError):
        raise malformed("body is not valid JSON")
    if not isinstance(value, dict):
        raise malformed("body must be a JSON object")
    return value


def encode(value):
    """Encode a response as UTF-8 JSON; fall back to ASCII escapes (D-12)."""
    try:
        return json.dumps(value, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(value).encode("ascii")


def _canon_number(value):
    if isinstance(value, int):
        if abs(value) < _BIG:
            return "i" + str(value)
        value = Decimal(value)
    if value == 0:
        return "i0"
    if value.is_finite() and value.adjusted() < 30 and value == value.to_integral_value():
        return "i" + str(int(value))
    return "d" + str(value.normalize())


def canonical(value):
    """Return a string equal for two bodies iff they are the same JSON value."""
    if value is None:
        return "n"
    if value is True:
        return "t"
    if value is False:
        return "f"
    if isinstance(value, str):
        return "s" + json.dumps(value)
    if isinstance(value, (int, Decimal)):
        return _canon_number(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items())
        return "{" + ",".join(json.dumps(k) + ":" + canonical(v) for k, v in items) + "}"
    raise TypeError(f"unexpected JSON value {type(value).__name__}")
