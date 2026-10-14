"""In-memory admin authentication.

The single admin user is defined by the ADMIN_USERNAME / ADMIN_PASSWORD
environment variables (see .env.example) — no database table involved.

Two credential styles are accepted on protected endpoints, via the standard
`Authorization` header:

- ``Basic base64(username:password)`` — the raw admin credentials.
- ``Bearer <token>`` — a token issued by POST /api/login. Tokens live only
  in this process's memory (lost on restart) and expire after TOKEN_TTL_SECONDS.
"""
from __future__ import annotations

import base64
import binascii
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from . import config

TOKEN_TTL_SECONDS = 12 * 3600


@dataclass
class _Session:
    username: str
    created_at: float


_sessions: dict[str, _Session] = {}


def _safe_equal(a: str, b: str) -> bool:
    try:
        return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return False


def verify_credentials(username: str, password: str) -> bool:
    """True only when both parts match the configured admin user."""
    expected_user = config.settings.admin_username
    expected_pass = config.settings.admin_password
    if not expected_user or not expected_pass:
        return False
    return _safe_equal(username, expected_user) and _safe_equal(password, expected_pass)


def issue_token(username: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = _Session(username=username, created_at=time.time())
    return token


def verify_token(token: str) -> bool:
    session = _sessions.get(token)
    if session is None:
        return False
    if time.time() - session.created_at > TOKEN_TTL_SECONDS:
        _sessions.pop(token, None)
        return False
    return True


def revoke_token(token: str) -> None:
    _sessions.pop(token, None)


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def is_admin_request(request: Request) -> bool:
    """True when the request carries valid admin credentials (Basic or Bearer)."""
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if not value.strip():
        return False
    if scheme.lower() == "bearer":
        return verify_token(value.strip())
    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
        username, sep, password = decoded.partition(":")
        if not sep:
            return False
        return verify_credentials(username, password)
    return False


def require_admin(request: Request) -> None:
    if not is_admin_request(request):
        raise HTTPException(
            status_code=401,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": 'Basic realm="admin"'},
        )
