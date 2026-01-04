from __future__ import annotations

import base64
import hashlib
import hmac
import os


_ALGO = "pbkdf2_sha256"
_ITERATIONS = 260_000
_SALT_BYTES = 16
_DKLEN = 32


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password is required")
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS, dklen=_DKLEN)
    return (
        f"{_ALGO}${_ITERATIONS}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii').rstrip('=')}$"
        f"{base64.urlsafe_b64encode(dk).decode('ascii').rstrip('=')}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iters_s, salt_b64, dk_b64 = encoded.split("$", 3)
        if algo != _ALGO:
            return False
        iters = int(iters_s)
        salt = base64.urlsafe_b64decode(_pad_b64(salt_b64))
        expected = base64.urlsafe_b64decode(_pad_b64(dk_b64))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _pad_b64(s: str) -> str:
    return s + "=" * (-len(s) % 4)

