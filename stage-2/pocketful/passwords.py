"""Owns password hashing: scrypt with per-user salt (R-40, D-13).

hashlib.scrypt releases the GIL, so hashing runs outside the global lock and a
large reset hashes on a small thread pool.
"""
import hashlib
import hmac
import os
from concurrent.futures import ThreadPoolExecutor

N, R, P = 2 ** 11, 8, 1
_DKLEN = 32
_WORKERS = max(2, min(4, os.cpu_count() or 2))


def _derive(password, salt, n, r, p):
    return hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                          n=n, r=r, p=p, dklen=_DKLEN, maxmem=64 * 1024 * 1024)


def hash_password(password):
    salt = os.urandom(16)
    digest = _derive(password, salt, N, R, P)
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


def hash_many(passwords):
    with ThreadPoolExecutor(_WORKERS) as pool:
        return list(pool.map(hash_password, passwords))


def is_valid_hash(stored):
    try:
        _parse(stored)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _parse(stored):
    scheme, n, r, p, salt, digest = stored.split("$")
    if scheme != "scrypt":
        raise ValueError("unknown scheme")
    n, r, p = int(n), int(r), int(p)
    if not (2 <= n <= 2 ** 16 and n & (n - 1) == 0 and 1 <= r <= 16 and 1 <= p <= 4):
        raise ValueError("scrypt parameters out of range")
    salt, digest = bytes.fromhex(salt), bytes.fromhex(digest)
    if len(digest) != _DKLEN or not salt:
        raise ValueError("bad digest")
    return n, r, p, salt, digest


def verify_password(password, stored):
    n, r, p, salt, digest = _parse(stored)
    return hmac.compare_digest(_derive(password, salt, n, r, p), digest)
