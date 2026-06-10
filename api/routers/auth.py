"""api/routers/auth.py — owner write unlock/lock (job_radar_SPEC §10.4, §10.5).

Adapted from cv-tailor's full_mode router. Validates the owner key once and issues a
signed HttpOnly capability cookie; the raw key never lives in the browser and isn't
re-sent per write. Enforcement of the cookie lives in the write routers (require_unlocked);
this router only mints/clears it. All checks fail closed (see api/security.py).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from api.security import (
    COOKIE_PATH,
    WRITE_COOKIE,
    WRITE_TTL,
    cookie_secure,
    issue_token,
    key_matches,
    write_configured,
)

router = APIRouter(prefix="/api", tags=["auth"])


class UnlockRequest(BaseModel):
    key: str


@router.post("/unlock")
def unlock(body: UnlockRequest, response: Response) -> dict:
    """Validate the owner key once; on success set the signed capability cookie.

    403 if owner-write isn't configured on this server (fail closed); 401 on a wrong key
    (no cookie set — the user stays read-only)."""
    if not write_configured():
        raise HTTPException(status_code=403, detail="owner write is not available on this server")
    if not key_matches(body.key):
        raise HTTPException(status_code=401, detail="incorrect unlock key")
    response.set_cookie(
        WRITE_COOKIE, issue_token(), max_age=WRITE_TTL, httponly=True,
        samesite="lax", secure=cookie_secure(), path=COOKIE_PATH,
    )
    return {"write_unlocked": True}


@router.post("/lock")
def lock(response: Response) -> dict:
    """Clear the capability cookie — re-lock owner writes for this browser."""
    response.delete_cookie(WRITE_COOKIE, path=COOKIE_PATH)
    return {"write_unlocked": False}
