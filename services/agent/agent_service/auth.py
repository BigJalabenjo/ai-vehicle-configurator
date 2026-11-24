"""Shared-password protection for the published app.

* The password comes from the APP_PASSWORD environment variable (never from code or the repo).
  If it is not set, protection is off (local development).
* A successful sign-in sets a signed, HTTP-only session cookie: "<expiry>.<hmac>". No server-side
  session store is needed, and changing APP_PASSWORD or APP_SECRET invalidates all cookies.
* nginx asks GET /api/auth/check before serving pages (auth_request); the API also enforces the
  cookie itself, so the protection does not depend on the web server alone.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings

COOKIE = "vc_session"
# Paths reachable without signing in: the auth endpoints themselves and the health check.
PUBLIC_PATHS = ("/api/auth/", "/api/health")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class Auth:
    def __init__(self, cfg: Settings):
        self.password = cfg.app_password
        self.ttl_s = int(cfg.auth_ttl_h * 3600)
        # Key for signing cookies. Derived from APP_SECRET (stable across restarts) plus the password,
        # so changing the password signs everyone out. Without APP_SECRET a random key is used and
        # sessions end when the service restarts.
        base = cfg.app_secret or secrets.token_hex(32)
        self.key = hashlib.sha256(f"{base}|{self.password or ''}".encode()).digest()

    @property
    def enabled(self) -> bool:
        return bool(self.password)

    def _sign(self, expiry: int) -> str:
        return hmac.new(self.key, str(expiry).encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        expiry = int(time.time()) + self.ttl_s
        return f"{expiry}.{self._sign(expiry)}"

    def valid(self, token: str | None) -> bool:
        if not self.enabled:
            return True
        if not token or "." not in token:
            return False
        expiry_s, sig = token.split(".", 1)
        if not expiry_s.isdigit() or int(expiry_s) < time.time():
            return False
        return hmac.compare_digest(sig, self._sign(int(expiry_s)))

    def check_password(self, attempt: str) -> bool:
        return bool(self.password) and hmac.compare_digest(attempt.encode(), self.password.encode())

    def is_public(self, path: str) -> bool:
        return not path.startswith("/api/") or path.startswith(PUBLIC_PATHS)


def secure_request(request: Request) -> bool:
    """Mark cookies Secure when the app is reached over HTTPS (directly or via a TLS proxy)."""
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def router(auth: Auth) -> APIRouter:
    r = APIRouter(prefix="/api/auth")

    @r.get("/status")
    async def status(request: Request):
        return {"enabled": auth.enabled, "authenticated": auth.valid(request.cookies.get(COOKIE))}

    @r.get("/check")
    async def check(request: Request):
        # Used by nginx auth_request: 204 = allowed, 401 = send to the login page.
        return Response(status_code=204 if auth.valid(request.cookies.get(COOKIE)) else 401)

    @r.post("/login")
    async def login(body: LoginRequest, request: Request):
        if not auth.enabled:
            return Response(status_code=204)
        if not auth.check_password(body.password):
            await asyncio.sleep(0.8)  # slows down guessing; nginx also rate-limits this endpoint
            return JSONResponse(status_code=401, content={"detail": "Incorrect password."})
        resp = Response(status_code=204)
        resp.set_cookie(COOKIE, auth.issue(), max_age=auth.ttl_s, httponly=True, samesite="strict",
                        secure=secure_request(request), path="/")
        return resp

    @r.post("/logout")
    async def logout(request: Request):
        resp = Response(status_code=204)
        resp.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=secure_request(request))
        return resp

    return r
