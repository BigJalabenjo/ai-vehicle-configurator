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
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from . import auth as auth_mod
from . import i18n
from .catalog_client import CatalogClient, CatalogError, CatalogUnavailable
from .llm_agent import LLMAgent, build_catalog_overview, system_prompt
from .config import Settings, settings
from .orchestrator import Orchestrator, TurnRequest
from .state import InMemorySessionStore
from .voice import AUDIO_TYPES, VoiceService, VoiceUnavailable

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agent")


class Runtime:
    """Lazily wires dependencies so the service starts even if the catalog is still booting."""

    def __init__(self, catalog: CatalogClient | None = None, llm_client=None, cfg: Settings = settings,
                 voice_client=None):
        self.cfg = cfg
        self.voice = VoiceService(cfg, voice_client)
        self._model_names: list[str] | None = None
        self.catalog = catalog or CatalogClient(cfg.catalog_url)
        self.sessions = InMemorySessionStore(cfg.session_ttl_s, cfg.max_sessions)
        self._llm_client = llm_client  # injectable SDK client (tests)
        self._orchestrator: Orchestrator | None = None
        self._lock = asyncio.Lock()

    async def orchestrator(self) -> Orchestrator:
        if self._orchestrator is None:
            async with self._lock:
                if self._orchestrator is None:
                    agent = None
                    if self.cfg.provider:
                        # The prompt's catalog overview is always English (ids, names); replies follow the session.
                        token = i18n.current.set(i18n.DEFAULT)
                        try:
                            catalog = await self.catalog.catalog()
                        finally:
                            i18n.current.reset(token)
                        prompt = system_prompt(build_catalog_overview(catalog))
                        agent = LLMAgent(self.cfg, make_provider(self.cfg, prompt, self._llm_client))
                    self._orchestrator = Orchestrator(self.catalog, agent)
                    log.info("agent mode=%s model=%s", self._orchestrator.mode, self.cfg.llm_model if agent else "-")
        return self._orchestrator

    async def model_names(self) -> list[str]:
        """Model names for putting right how speech recognition spells them (the same in every language)."""
        if self._model_names is None:
            self._model_names = [m["name"] for m in (await self.catalog.catalog())["models"]]
        return self._model_names


class SpeechRequest(BaseModel):
    text: str


class NewSessionRequest(BaseModel):
    language: i18n.Language = i18n.DEFAULT


def make_provider(cfg: Settings, prompt: str, client=None):
    if cfg.provider == "anthropic":
        from .providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(cfg.llm_model, prompt, cfg.llm_effort, cfg.llm_timeout_s, cfg.llm_server_fallback, client)
    from .providers.openai_provider import OpenAIProvider
    return OpenAIProvider(cfg.llm_model, prompt, cfg.llm_effort, cfg.llm_timeout_s, client)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    rt = runtime or Runtime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await rt.catalog.close()

    app = FastAPI(title="Vehicle Configurator Agent", version="1.0.0", lifespan=lifespan)
    app.state.runtime = rt
    auth = auth_mod.Auth(rt.cfg)
    log.info("password protection %s", "enabled" if auth.enabled else "disabled (APP_PASSWORD not set)")
    app.include_router(auth_mod.router(auth))

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        # Defence in depth: the API enforces sign-in itself, independent of the web server.
        if auth.enabled and not auth.is_public(request.url.path) and not auth.valid(request.cookies.get(auth_mod.COOKIE)):
            return JSONResponse(status_code=401, content={"detail": "Please sign in."})
        return await call_next(request)
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
                "mode": orch.mode if orch else (rt.cfg.provider or "guided")}

    @app.post("/api/sessions", status_code=201)
    async def create_session(body: NewSessionRequest | None = None):
        orch = await rt.orchestrator()
        state = await rt.sessions.create()
        state.language = (body or NewSessionRequest()).language
        i18n.use(state.language)
        message = orch.greeting(state)
        await rt.sessions.save(state)
        return {"session_id": state.id, "mode": orch.mode, "voice": rt.voice.enabled, "message": message,
                "state": await orch.snapshot(state)}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        orch = await rt.orchestrator()
        state = await rt.sessions.get(session_id)
        if not state:
            raise HTTPException(404, "Session not found or expired")
        i18n.use(state.language)
        return {"session_id": state.id, "mode": orch.mode, "voice": rt.voice.enabled, "transcript": state.transcript,
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
            i18n.use(state.language)  # replies, catalog texts and rule messages in the customer's language
            # A turn is all-or-nothing: if it fails partway (e.g. a backend error after the model was
            # already selected), restore the previous state instead of keeping half an update.
            backup = state.model_copy(deep=True)
            try:
                result = await orch.handle(state, body)
            except Exception:
                await rt.sessions.save(backup)
                raise
            await rt.sessions.save(state)
        return {"session_id": session_id, **result}

    # ---------------------------------------------------------------- voice
    # Turn-based voice: the browser detects when the customer stops talking, sends the recording here,
    # and posts the recognised text to /turn like typed text. Replies are read out via /voice/speech.

    async def voice_session(session_id: str) -> None:
        if not rt.voice.enabled:
            raise HTTPException(404, "Voice is not enabled")
        state = await rt.sessions.get(session_id)
        if not state:
            raise HTTPException(404, "Session not found or expired")
        i18n.use(state.language)  # listen and speak in the session's language

    @app.post("/api/sessions/{session_id}/voice/transcribe")
    async def transcribe(session_id: str, request: Request):
        await voice_session(session_id)
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in AUDIO_TYPES:
            raise HTTPException(415, "Unsupported audio format")
        limit = rt.cfg.voice_max_audio_bytes
        if int(request.headers.get("content-length") or 0) > limit:
            raise HTTPException(413, i18n.t("voice_too_long"))
        audio = bytearray()
        async for chunk in request.stream():
            audio += chunk
            if len(audio) > limit:
                raise HTTPException(413, i18n.t("voice_too_long"))
        if not audio:
            raise HTTPException(422, i18n.t("voice_empty"))
        try:
            text = await rt.voice.transcribe(bytes(audio), content_type, i18n.lang(), await rt.model_names())
        except VoiceUnavailable as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"text": text[: rt.cfg.max_message_chars]}

    @app.post("/api/sessions/{session_id}/voice/speech")
    async def speech(session_id: str, body: SpeechRequest):
        await voice_session(session_id)
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "Nothing to say")
        if len(text) > rt.cfg.voice_max_speech_chars:
            raise HTTPException(413, "Text too long")
        try:
            audio = await rt.voice.speak(text, i18n.lang())
        except VoiceUnavailable as exc:
            raise HTTPException(502, str(exc)) from exc
        return Response(audio, media_type="audio/mpeg", headers={"cache-control": "no-store"})

    return app


app = create_app()
