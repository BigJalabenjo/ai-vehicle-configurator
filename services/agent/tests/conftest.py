"""Test wiring: the agent talks to the *real* catalog service in-process via ASGI transport."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "catalog"))  # make catalog_service importable for integration tests

from catalog_service.main import app as catalog_app  # noqa: E402

from agent_service.catalog_client import CatalogClient  # noqa: E402
from agent_service.config import Settings  # noqa: E402
from agent_service.main import Runtime, create_app  # noqa: E402


@pytest.fixture
def catalog_client() -> CatalogClient:
    return CatalogClient("http://catalog", transport=httpx.ASGITransport(app=catalog_app))


def make_client(catalog_client: CatalogClient, mode: str = "offline", claude_client=None) -> httpx.AsyncClient:
    cfg = Settings(agent_mode=mode)  # type: ignore[arg-type]
    app = create_app(Runtime(catalog=catalog_client, claude_client=claude_client, cfg=cfg))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent")


@pytest_asyncio.fixture
async def agent(catalog_client):
    async with make_client(catalog_client) as client:
        yield client
