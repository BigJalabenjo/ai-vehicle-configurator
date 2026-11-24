import pytest
from fastapi.testclient import TestClient

from catalog_service.main import app
from catalog_service.recommender import recommend
from catalog_service.repository import CatalogRepository
from catalog_service.rules import ConfigurationEngine
from catalog_service.schemas import Requirements

FAMILY = Requirements(budget_max=85000, powertrain_preferred=["bev"], child_seats=3, long_distance=True)


@pytest.fixture(scope="module")
def engine() -> ConfigurationEngine:
    return ConfigurationEngine(CatalogRepository.from_file())


def test_reference_scenario_ranks_electric_estate_first(engine):
    res = recommend(engine, FAMILY)
    assert res.fits[0].model_id == "i5_touring_edrive40"
    assert all(e.entry_price <= 85000 for e in res.fits)
    assert all(e.specs["rear_three_child_seats"] for e in res.fits)
    assert res.fits[0].reasons  # explainable


def test_near_miss_over_budget_becomes_tradeoff(engine):
    res = recommend(engine, FAMILY)
    ix = next(e for e in res.near_misses if e.model_id == "ix_xdrive45")
    assert [v.code for v in ix.violations] == ["budget"]
    trade = next(t for t in res.tradeoffs if t.model_id == "ix_xdrive45")
    assert trade.relax_patch == {"budget_max": 86900}


def test_unsatisfiable_requirements_return_tradeoffs_not_empty(engine):
    req = FAMILY.model_copy(update={"min_seats": 7})
    res = recommend(engine, req)
    assert res.fits == []
    assert res.tradeoffs
    x5 = next(t for t in res.tradeoffs if t.model_id == "x5_xdrive50e")
    assert x5.relax_patch == {"budget_max": 84500 + 1850 + 950}  # third row + its required climate


def test_capability_requirements_add_needed_options_to_price(engine):
    res = recommend(engine, Requirements(towing_kg=1500, budget_max=200000))
    i5 = next(e for e in res.fits + res.near_misses if e.model_id == "i5_touring_edrive40")
    assert "tow_hitch" in i5.required_options
    assert i5.entry_price == 71900 + 1150


def test_hard_powertrain_filter(engine):
    res = recommend(engine, Requirements(powertrain_required=["bev"]), limit=10)
    assert {e.powertrain for e in res.fits} == {"bev"}


def test_long_distance_rejects_short_range_bev(engine):
    res = recommend(engine, Requirements(long_distance=True), model_ids=["ix1_xdrive30"])
    assert res.near_misses[0].violations[0].code == "range"


def test_view_reports_unmet_requirements(engine):
    view = engine.view("i4_edrive40", [], FAMILY)
    assert any(v.code == "child_seats" for v in view.unmet_requirements)


def test_api_roundtrip():
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    r = client.post("/v1/recommendations", json={"requirements": FAMILY.model_dump()})
    assert r.status_code == 200 and r.json()["fits"]
    r = client.post("/v1/configurations/change", json={
        "model_id": "i4_edrive40", "options": [], "change": {"action": "add", "option_id": "tow_hitch"}})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post("/v1/configurations/view", json={"model_id": "nope"}).status_code == 404
    assert client.post("/v1/recommendations", json={"requirements": {"budget_max": -5}}).status_code == 422
