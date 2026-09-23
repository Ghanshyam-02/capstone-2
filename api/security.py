"""API-key authentication.

Every /api/v1 endpoint requires the header  X-API-Key: <key from .env>.
In a real bank this would be replaced by SSO / OAuth2 tokens at an API gateway.
"""
import os
import secrets

from fastapi import Header, HTTPException, status


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("API_KEY")
    if not expected:
        # Fail closed: if the server is mis-configured, nobody gets in.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API key not configured on server")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")
