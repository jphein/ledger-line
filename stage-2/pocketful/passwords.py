"""Owns password hashing: scrypt (R-40, D-13) and bulk fixture hashing (D-208).

hashlib.scrypt releases the GIL, so hashing runs outside the global lock and a
large reset hashes on a thread pool sized to the CPUs the process may actually
use: inside a container os.cpu_count() reports the host, not the cgroup quota.
A reset hashes each distinct fixture password once; users sharing a password
within that fixture share its salt. Signups always get their own salt.
"""
import hashlib
import hmac
import math
import os
from concurrent.futures import ThreadPoolExecutor

N, R, P = 2 ** 11, 8, 1
_DKLEN = 32


def _quota_cpus():
    """CPUs granted by the cgroup quota (v2, then v1), or None when unlimited."""
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()[:2]
    except (OSError, ValueError):
        try:
            with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
                quota = f.read().strip()
            with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
                period = f.read().strip()
        except OSError:
            return None
    try:
        quota, period = int(quota), int(period)
    except ValueError:  # "max": no quota
        return None
    return math.ceil(quota / period) if quota > 0 and period > 0 else None


def usable_cpus():
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    quota = _quota_cpus()
    return max(1, min(cpus or 1, quota or cpus or 1))


_WORKERS = min(8, usable_cpus())


def _derive(password, salt, n, r, p):
    return hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                          n=n, r=r, p=p, dklen=_DKLEN, maxmem=64 * 1024 * 1024)


def hash_password(password):
    salt = os.urandom(16)
    digest = _derive(password, salt, N, R, P)
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


def hash_many(passwords):
    """Hash a fixture's passwords: one scrypt per distinct password (D-208)."""
    distinct = list(dict.fromkeys(passwords))
    if not distinct:
        return []
    if len(distinct) == 1:
        hashed = [hash_password(distinct[0])]
    else:
        with ThreadPoolExecutor(min(_WORKERS, len(distinct))) as pool:
            hashed = list(pool.map(hash_password, distinct))
    by_password = dict(zip(distinct, hashed))
    return [by_password[password] for password in passwords]


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
