"""Catalog & configuration service (stand-in for BMW product, pricing and rules backends)."""

from __future__ import annotations

import logging
import os
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .recommender import recommend
from .repository import CatalogRepository
from .rules import ConfigurationEngine, UnknownModelError
from .schemas import (
    Catalog,
    ChangeConfigurationRequest,
    ChangeResult,
    ConfigurationRequest,
    ConfigurationView,
    RecommendRequest,
    RecommendResponse,
    SwitchModelRequest,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s catalog %(message)s")
log = logging.getLogger("catalog")

repo = CatalogRepository.from_file()
engine = ConfigurationEngine(repo)

app = FastAPI(title="Vehicle Catalog & Configuration Service", version="1.0.0")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    log.info("%s %s -> %s in %.1fms request_id=%s", request.method, request.url.path, response.status_code,
             (time.perf_counter() - start) * 1000, request_id)
    return response


@app.exception_handler(UnknownModelError)
async def unknown_model_handler(_request: Request, exc: UnknownModelError):
    return JSONResponse(status_code=404, content={"detail": f"Unknown model '{exc.args[0]}'"})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "catalog_version": repo.catalog.version, "models": len(repo.models), "options": len(repo.options)}


@app.get("/v1/catalog", response_model=Catalog)
def get_catalog() -> Catalog:
    return repo.catalog


@app.get("/v1/models/{model_id}")
def get_model(model_id: str):
    model = repo.models.get(model_id)
    if not model:
        raise HTTPException(404, f"Unknown model '{model_id}'")
    return model


@app.post("/v1/recommendations", response_model=RecommendResponse)
def post_recommendations(body: RecommendRequest) -> RecommendResponse:
    return recommend(engine, body.requirements, body.model_ids, body.limit)


@app.post("/v1/configurations/view", response_model=ConfigurationView)
def post_view(body: ConfigurationRequest) -> ConfigurationView:
    return engine.view(body.model_id, body.options, body.requirements)


@app.post("/v1/configurations/change", response_model=ChangeResult)
def post_change(body: ChangeConfigurationRequest) -> ChangeResult:
    return engine.apply(body.model_id, body.options, body.change, body.requirements)


@app.post("/v1/configurations/switch-model", response_model=ChangeResult)
def post_switch(body: SwitchModelRequest) -> ChangeResult:
    return engine.switch_model(body.new_model_id, body.previous_options, body.requirements)
