"""Shared-password protection: API enforcement, sign-in, sign-out, cookie handling."""

import time

import httpx
import pytest

from agent_service.auth import COOKIE, Auth
from agent_service.config import Settings
from agent_service.main import Runtime, create_app

pytestmark = pytest.mark.asyncio

PASSWORD = "test-only-password"


def client(catalog_client, password: str | None = PASSWORD) -> httpx.AsyncClient:
    cfg = Settings(agent_mode="offline", app_password=password, app_secret="test-secret")  # type: ignore[arg-type]
    app = create_app(Runtime(catalog=catalog_client, cfg=cfg))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent")


async def test_open_when_no_password_is_set(catalog_client):
    async with client(catalog_client, password=None) as c:
        assert (await c.get("/api/auth/status")).json() == {"enabled": False, "authenticated": True}
        assert (await c.get("/api/auth/check")).status_code == 204
        assert (await c.post("/api/sessions")).status_code == 201


async def test_api_requires_sign_in(catalog_client):
    async with client(catalog_client) as c:
        assert (await c.post("/api/sessions")).status_code == 401
        assert (await c.get("/api/auth/check")).status_code == 401
        assert (await c.get("/api/health")).status_code == 200  # health stays public for container checks
        assert (await c.get("/api/auth/status")).json() == {"enabled": True, "authenticated": False}


async def test_wrong_password_is_rejected(catalog_client):
    async with client(catalog_client) as c:
        r = await c.post("/api/auth/login", json={"password": "guess"})
        assert r.status_code == 401 and COOKIE not in r.cookies
        assert (await c.post("/api/sessions")).status_code == 401


async def test_sign_in_and_out(catalog_client):
    async with client(catalog_client) as c:
        r = await c.post("/api/auth/login", json={"password": PASSWORD})
        assert r.status_code == 204
        set_cookie = r.headers["set-cookie"].lower()
        assert "httponly" in set_cookie and "samesite=strict" in set_cookie
        assert "secure" not in set_cookie  # plain http in tests
        assert (await c.get("/api/auth/check")).status_code == 204
        assert (await c.post("/api/sessions")).status_code == 201

        await c.post("/api/auth/logout")
        assert (await c.post("/api/sessions")).status_code == 401


async def test_cookie_is_secure_behind_https_proxy(catalog_client):
    async with client(catalog_client) as c:
        r = await c.post("/api/auth/login", json={"password": PASSWORD}, headers={"x-forwarded-proto": "https"})
        assert "secure" in r.headers["set-cookie"].lower()


async def test_forged_or_expired_tokens_are_rejected():
    cfg = Settings(app_password=PASSWORD, app_secret="test-secret", auth_ttl_h=1)  # type: ignore[arg-type]
    auth = Auth(cfg)
    good = auth.issue()
    assert auth.valid(good)
    expiry, sig = good.split(".")
    assert not auth.valid(f"{int(expiry) + 3600}.{sig}")               # extended expiry, old signature
    assert not auth.valid(f"{int(time.time()) - 1}.{auth._sign(int(time.time()) - 1)}")  # expired
    assert not auth.valid("garbage") and not auth.valid(None)
    # changing the password invalidates existing sessions
    other = Auth(Settings(app_password="new-password", app_secret="test-secret"))  # type: ignore[arg-type]
    assert not other.valid(good)


async def test_embedded_mode_uses_partitioned_cross_site_cookie(catalog_client):
    cfg = Settings(agent_mode="offline", app_password=PASSWORD, app_secret="s",  # type: ignore[arg-type]
                   embed_origins=["https://configure.bmw.de"])
    app = create_app(Runtime(catalog=catalog_client, cfg=cfg))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as c:
        r = await c.post("/api/auth/login", json={"password": PASSWORD})
        cookie = r.headers["set-cookie"].lower()
        assert "samesite=none" in cookie and "secure" in cookie and "partitioned" in cookie and "httponly" in cookie
