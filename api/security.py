"""api/security.py — owner write-unlock capability cookie (job_radar_SPEC §10.5).

Adapted from cv-tailor's api/security.py (D-38/D-39, proven in production). The public
deployment is read-only; the owner submits ``JR_WRITE_KEY`` once and the backend issues
a signed capability cookie that proves "unlocked until <exp>". Workflow + annotation
writes are then gated on the cookie — the raw key never lives in the browser and isn't
re-sent per write.

The token is signed with stdlib HMAC-SHA256 (no dependency — the spec's step-8 mention
of ``itsdangerous`` is superseded by copying cv-tailor's zero-dep module; logged as a
deviation) using ``JR_WRITE_KEY`` itself as the secret: the cookie carries only a
signature, never the key, and rotating the key invalidates every outstanding cookie.
Everything **fails closed** — no key configured, or a missing/tampered/expired token,
means "not unlocked". The backend is the source of truth (the write routers enforce it);
UI hiding is convenience only. The CLI (cli.track) is unaffected — it has no cookie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request

__all__ = [
    "WRITE_COOKIE", "WRITE_TTL", "COOKIE_PATH", "cookie_secure", "write_configured",
    "key_matches", "issue_token", "verify_token", "require_unlocked",
]

WRITE_COOKIE = "jr_write"
WRITE_TTL = 7 * 24 * 3600          # 7 days — owner convenience vs. exposure window
COOKIE_PATH = "/api"


def _key() -> str:
    """The owner write key from the environment (the signing secret), or '' if unset."""
    return os.environ.get("JR_WRITE_KEY", "")


def write_configured() -> bool:
    """True when the server has a JR_WRITE_KEY — i.e. writes can be unlocked at all."""
    return bool(_key())


def cookie_secure() -> bool:
    """Whether to mark the capability cookie Secure. Off by default (localhost http);
    set COOKIE_SECURE=true in prod (the browser↔proxy leg is HTTPS)."""
    return os.environ.get("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")


def key_matches(candidate: str | None) -> bool:
    """Constant-time check of a submitted unlock key against JR_WRITE_KEY."""
    key = _key()
    if not key or not candidate:
        return False
    return hmac.compare_digest(candidate, key)


def _sign(exp: int, secret: str) -> str:
    sig = hmac.new(secret.encode(), str(exp).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def issue_token(*, now: int | None = None) -> str:
    """Mint a capability token ``"<exp>.<b64sig>"``. Caller must have verified the key
    first; raises if no key is configured, so a token is never minted unsigned."""
    secret = _key()
    if not secret:
        raise RuntimeError("cannot issue a write token: JR_WRITE_KEY is not set")
    exp = (int(time.time()) if now is None else now) + WRITE_TTL
    return f"{exp}.{_sign(exp, secret)}"


def verify_token(token: str | None, *, now: int | None = None) -> bool:
    """True iff ``token`` is a well-formed, unexpired capability token signed with the
    current JR_WRITE_KEY. Fails closed on anything off (no key, malformed, expired,
    bad signature)."""
    secret = _key()
    if not secret or not token or "." not in token:
        return False
    exp_str, _, sig = token.partition(".")
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    if exp < (int(time.time()) if now is None else now):
        return False
    return hmac.compare_digest(sig, _sign(exp, secret))


def require_unlocked(request: Request) -> None:
    """FastAPI dependency gating every state-mutating endpoint on the capability cookie.

    Fails closed: 403 when no key is configured on the server (the deployment is
    read-only) or the request carries no valid capability cookie. Use as
    ``dependencies=[Depends(require_unlocked)]`` so it runs before the handler — a
    refused write never validates or appends a corpus line."""
    if not write_configured():
        raise HTTPException(
            status_code=403,
            detail="this deployment is read-only (owner unlock not configured)",
        )
    if not verify_token(request.cookies.get(WRITE_COOKIE)):
        raise HTTPException(
            status_code=403,
            detail="locked — unlock owner access to modify the corpus",
        )
