"""Fail-closed shared bearer-token authentication."""

from __future__ import annotations

import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


_bearer = HTTPBearer(auto_error=False)
_MIN_TOKEN_LENGTH = 32


def require_manager_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Require the server-side manager API token for every v1 route."""

    expected = os.getenv("MANAGER_API_TOKEN", "").strip()
    if len(expected) < _MIN_TOKEN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Manager API authentication is not configured.",
        )

    supplied = credentials.credentials if credentials is not None else ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
