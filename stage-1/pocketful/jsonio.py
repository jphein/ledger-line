"""Owns JSON at the boundary: strict parsing, response encoding, canonical body form.

Floats parse as Decimal so `1e3`, `1000.0` and huge exponents stay exact and never
become inf. The canonical form drives replay comparison (D-11): type-aware,
recursive and exact at every magnitude, so a bool never equals a number while
`1000` equals `1000.0` and `1e3`.
"""
import json
from decimal import Decimal, InvalidOperation

from .errors import malformed


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


def exact_number(value):
    """(sign, digits, exponent) with trailing zeros moved into the exponent.

    Pure digit manipulation, no decimal context: exact at every magnitude and
    never raises, so two numbers get the same triple iff they are equal.
    Zero is (0, "0", 0) whatever its sign or exponent.
    """
    if isinstance(value, int):
        sign, digits, exponent = int(value < 0), str(abs(value)), 0
    else:
        sign, digit_tuple, exponent = value.as_tuple()
        digits = "".join(map(str, digit_tuple))
    stripped = digits.rstrip("0")
    if not stripped:
        return 0, "0", 0
    return sign, stripped, exponent + len(digits) - len(stripped)


def canonical(value):
    """Return a string equal for two bodies iff they are the same JSON value.

    Iterative (explicit stack), so arbitrarily deep bodies never hit the
    recursion limit. Tuples on the stack are literal output; JSON has no tuples.
    """
    out = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, tuple):
            out.append(item[0])
        elif item is None:
            out.append("n")
        elif item is True:
            out.append("t")
        elif item is False:
            out.append("f")
        elif isinstance(item, str):
            out.append("s" + json.dumps(item))
        elif isinstance(item, (int, Decimal)):
            sign, digits, exponent = exact_number(item)
            out.append(f"#{sign}:{digits}e{exponent}")
        elif isinstance(item, list):
            out.append("[")
            stack.append(("]",))
            for index in range(len(item) - 1, -1, -1):
                stack.append(item[index])
                if index:
                    stack.append((",",))
        elif isinstance(item, dict):
            out.append("{")
            stack.append(("}",))
            pairs = sorted(item.items(), key=lambda pair: pair[0])
            for index in range(len(pairs) - 1, -1, -1):
                key, member = pairs[index]
                stack.append(member)
                stack.append((json.dumps(key) + ":",))
                if index:
                    stack.append((",",))
        else:
            raise TypeError(f"unexpected JSON value {type(item).__name__}")
    return "".join(out)
