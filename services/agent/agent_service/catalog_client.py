"""HTTP client for the catalog / configuration service, with timeouts and retries."""

from __future__ import annotations

import asyncio
import logging

import httpx

from . import i18n
from .domain import Requirements

log = logging.getLogger("agent.catalog")


class CatalogUnavailable(RuntimeError):
    """The catalog service could not be reached (after retries)."""


class CatalogError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"catalog error {status}: {detail}")
        self.status = status
        self.detail = detail


class CatalogClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 5.0, retries: int = 2):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)
        self._retries = retries
        self._catalog: dict[str, dict] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, json: dict | None = None, request_id: str | None = None) -> dict:
        # The catalog answers in the session's language (names, rule messages, reasons).
        headers = {"accept-language": i18n.lang(), **({"x-request-id": request_id} if request_id else {})}
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.request(method, path, json=json, headers=headers)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
                if attempt == self._retries:
                    raise CatalogUnavailable(str(exc)) from exc
                await asyncio.sleep(0.2 * 2**attempt)
                continue
            if resp.status_code >= 500 and attempt < self._retries:
                await asyncio.sleep(0.2 * 2**attempt)
                continue
            if resp.status_code >= 400:
                detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                raise CatalogError(resp.status_code, str(detail))
            return resp.json()
        raise CatalogUnavailable("exhausted retries")  # pragma: no cover

    async def health(self) -> dict:
        return await self._request("GET", "/health")

    async def catalog(self) -> dict:
        """The catalog in the current language (cached per language)."""
        code = i18n.lang()
        if code not in self._catalog:
            self._catalog[code] = await self._request("GET", "/v1/catalog")
        return self._catalog[code]

    async def recommend(self, req: Requirements, model_ids: list[str] | None = None, limit: int = 3) -> dict:
        return await self._request("POST", "/v1/recommendations",
                                   {"requirements": req.model_dump(), "model_ids": model_ids, "limit": limit})

    async def view(self, model_id: str, options: list[str], req: Requirements) -> dict:
        return await self._request("POST", "/v1/configurations/view",
                                   {"model_id": model_id, "options": options, "requirements": req.model_dump()})

    async def change(self, model_id: str, options: list[str], req: Requirements,
                     action: str, option_id: str, force: bool = False) -> dict:
        return await self._request("POST", "/v1/configurations/change", {
            "model_id": model_id, "options": options, "requirements": req.model_dump(),
            "change": {"action": action, "option_id": option_id, "force": force},
        })

    async def switch_model(self, new_model_id: str, previous_options: list[str], req: Requirements) -> dict:
        return await self._request("POST", "/v1/configurations/switch-model", {
            "new_model_id": new_model_id, "previous_options": previous_options, "requirements": req.model_dump(),
        })
