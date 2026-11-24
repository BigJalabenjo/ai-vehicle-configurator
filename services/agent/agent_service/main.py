"""Agent service API (BFF for the web client)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .catalog_client import CatalogClient, CatalogError, CatalogUnavailable
from .claude_agent import ClaudeAgent, build_catalog_overview
from .config import Settings, settings
from .orchestrator import Orchestrator, TurnRequest
from .state import InMemorySessionStore

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agent")


class Runtime:
    """Lazily wires dependencies so the service starts even if the catalog is still booting."""

    def __init__(self, catalog: CatalogClient | None = None, claude_client=None, cfg: Settings = settings):
        self.cfg = cfg
        self.catalog = catalog or CatalogClient(cfg.catalog_url)
        self.sessions = InMemorySessionStore(cfg.session_ttl_s, cfg.max_sessions)
        self._claude_client = claude_client
        self._orchestrator: Orchestrator | None = None
        self._lock = asyncio.Lock()

    async def orchestrator(self) -> Orchestrator:
        if self._orchestrator is None:
            async with self._lock:
                if self._orchestrator is None:
                    claude = None
                    if self.cfg.use_claude:
                        overview = build_catalog_overview(await self.catalog.catalog())
                        claude = ClaudeAgent(self.cfg, overview, client=self._claude_client)
                    self._orchestrator = Orchestrator(self.catalog, claude)
                    log.info("agent mode=%s model=%s", self._orchestrator.mode, self.cfg.llm_model if claude else "-")
        return self._orchestrator


def create_app(runtime: Runtime | None = None) -> FastAPI:
    rt = runtime or Runtime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await rt.catalog.close()

    app = FastAPI(title="Vehicle Configurator Agent", version="1.0.0", lifespan=lifespan)
    app.state.runtime = rt
    app.add_middleware(CORSMiddleware, allow_origins=rt.cfg.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["content-type", "x-request-id"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        # Privacy: log metadata only, never message content.
        log.info("%s %s -> %s in %.0fms request_id=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000, request_id)
        return response

    @app.exception_handler(CatalogUnavailable)
    async def catalog_down(_req: Request, exc: CatalogUnavailable):
        log.error("catalog unavailable: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "The vehicle catalog is temporarily unavailable. Please retry."})

    @app.exception_handler(CatalogError)
    async def catalog_error(_req: Request, exc: CatalogError):
        status = 400 if exc.status < 500 else 502
        return JSONResponse(status_code=status, content={"detail": exc.detail})

    @app.get("/api/health")
    async def health():
        orch = rt._orchestrator
        try:
            catalog = await rt.catalog.health()
            catalog_status = catalog["status"]
        except (CatalogUnavailable, CatalogError):
            catalog_status = "unavailable"
        return {"status": "ok" if catalog_status == "ok" else "degraded", "catalog": catalog_status,
                "mode": orch.mode if orch else ("claude" if rt.cfg.use_claude else "guided")}

    @app.post("/api/sessions", status_code=201)
    async def create_session():
        orch = await rt.orchestrator()
        state = await rt.sessions.create()
        message = orch.greeting(state)
        await rt.sessions.save(state)
        return {"session_id": state.id, "mode": orch.mode, "message": message, "state": await orch.snapshot(state)}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        orch = await rt.orchestrator()
        state = await rt.sessions.get(session_id)
        if not state:
            raise HTTPException(404, "Session not found or expired")
        return {"session_id": state.id, "mode": orch.mode, "transcript": state.transcript,
                "state": await orch.snapshot(state)}

    @app.post("/api/sessions/{session_id}/turn")
    async def turn(session_id: str, body: TurnRequest):
        if not body.message and not body.action:
            raise HTTPException(422, "Provide a message or an action")
        if body.message and len(body.message) > rt.cfg.max_message_chars:
            raise HTTPException(413, "Message too long")
        orch = await rt.orchestrator()
        async with rt.sessions.lock(session_id):
            state = await rt.sessions.get(session_id)
            if not state:
                raise HTTPException(404, "Session not found or expired")
            result = await orch.handle(state, body)
            await rt.sessions.save(state)
        return {"session_id": session_id, **result}

    return app


app = create_app()
