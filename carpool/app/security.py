"""Hashing de contraseñas, CSRF, limitación de intentos y códigos de invitación."""

import secrets
import string
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_ph = PasswordHasher()

ALFABETO = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_invite_code(length: int = 8) -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(length))


# --- CSRF -------------------------------------------------------------
def ensure_csrf(session_dict) -> str:
    token = session_dict.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        session_dict["csrf"] = token
    return token


def csrf_ok(session_dict, token: str | None) -> bool:
    expected = session_dict.get("csrf")
    return bool(expected and token and secrets.compare_digest(expected, token))


# --- Rate limit en memoria -------------------------------------------
# Suficiente para una instancia única. Si algún día escalas a varias
# réplicas, muévelo a Redis.
_hits: Dict[str, Deque[float]] = defaultdict(deque)


def rate_limited(key: str, limit: int = 8, window: int = 300) -> bool:
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False
