"""Owns password hashing: scrypt (R-40, D-13) and bulk fixture hashing (D-208).

hashlib.scrypt releases the GIL, so hashing runs outside the global lock and a
large reset hashes on a thread pool sized to the CPUs the process may actually
use: inside a container os.cpu_count() reports the host, not the cgroup quota.
A reset runs scrypt once per distinct fixture password and stores each user as
sha256(user_salt || scrypt(pw, shared_salt)), so records stay per-user (D-208).
Signups always get a plain scrypt hash with their own salt.
"""
import hashlib
import hmac
import math
import os
from concurrent.futures import ThreadPoolExecutor

N, R, P = 2 ** 11, 8, 1
# D-215: fixture-seeded users may use a cheaper cost so a 1000-user reset with
# distinct passwords fits the 10 s limit in a 2 vCPU container. The cost is
# stored in each record, so verification always uses the record's own n.
FIXTURE_N = 2 ** 10  # container: 2^11 measured 6.24-8.34 s for 1000 distinct; 2^10 ~5 ms/hash single-thread
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


def _wrap(shared_salt, derived, n):
    """Per-user record over a shared derivation: sha256(user_salt || scrypt key)."""
    user_salt = os.urandom(16)
    digest = hashlib.sha256(user_salt + derived).digest()
    return (f"scrypt-sha256${n}${R}${P}${shared_salt.hex()}${user_salt.hex()}"
            f"${digest.hex()}")


def hash_many(passwords):
    """Hash a fixture's passwords (D-208, D-215).

    One shared salt per reset, so the stored shared-salt field is identical for
    every seeded user and says nothing about equal passwords; one scrypt per
    distinct password (FIXTURE_N), in a pool; then a per-user salted sha256 so
    every record is unique.
    """
    shared_salt = os.urandom(16)
    distinct = list(dict.fromkeys(passwords))
    derive = lambda pw: _derive(pw, shared_salt, FIXTURE_N, R, P)  # noqa: E731
    if len(distinct) <= 1:
        derived = [derive(pw) for pw in distinct]
    else:
        with ThreadPoolExecutor(min(_WORKERS, len(distinct))) as pool:
            derived = list(pool.map(derive, distinct))
    by_password = dict(zip(distinct, derived))
    return [_wrap(shared_salt, by_password[pw], FIXTURE_N) for pw in passwords]


def is_valid_hash(stored):
    try:
        _parse(stored)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _parse(stored):
    """-> (n, r, p, scrypt salt, user salt or None, digest)."""
    parts = stored.split("$")
    if parts[0] == "scrypt" and len(parts) == 6:
        _, n, r, p, salt, digest = parts
        user_salt = None
    elif parts[0] == "scrypt-sha256" and len(parts) == 7:
        _, n, r, p, salt, user_salt, digest = parts
        user_salt = bytes.fromhex(user_salt)
        if not user_salt:
            raise ValueError("bad user salt")
    else:
        raise ValueError("unknown scheme")
    n, r, p = int(n), int(r), int(p)
    if not (2 <= n <= 2 ** 16 and n & (n - 1) == 0 and 1 <= r <= 16 and 1 <= p <= 4):
        raise ValueError("scrypt parameters out of range")
    salt, digest = bytes.fromhex(salt), bytes.fromhex(digest)
    if len(digest) != _DKLEN or not salt:
        raise ValueError("bad digest")
    return n, r, p, salt, user_salt, digest


def verify_password(password, stored):
    n, r, p, salt, user_salt, digest = _parse(stored)
    derived = _derive(password, salt, n, r, p)
    if user_salt is not None:
        derived = hashlib.sha256(user_salt + derived).digest()
    return hmac.compare_digest(derived, digest)
