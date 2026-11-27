"""German catalog texts and rule messages, chosen per request with Accept-Language."""

import pytest
from fastapi.testclient import TestClient

from catalog_service import i18n
from catalog_service.main import app

I5 = "i5_touring_edrive40"
DE = {"accept-language": "de-DE,de;q=0.9"}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.mark.parametrize("header, expected", [
    (None, "en"), ("de", "de"), ("de-AT,en;q=0.5", "de"), ("en-GB,de;q=0.8", "en"), ("fr-FR", "en"),
])
def test_language_is_picked_from_accept_language(header, expected):
    assert i18n.pick(header) == expected


def test_every_message_has_a_german_version():
    assert i18n.MESSAGES["en"].keys() == i18n.MESSAGES["de"].keys()


def test_catalog_is_served_in_german_and_ids_stay_the_same(client):
    en = client.get("/v1/catalog").json()
    de = client.get("/v1/catalog", headers=DE).json()
    assert [o["id"] for o in en["options"]] == [o["id"] for o in de["options"]]
    assert [o["price"] for o in en["options"]] == [o["price"] for o in de["options"]]
    assert en["disclaimer"] != de["disclaimer"]
    changed = sum(a["name"] != b["name"] for a, b in zip(en["options"], de["options"]))
    assert changed > 0, "option names are translated"


def test_language_does_not_leak_between_requests(client):
    client.get("/v1/catalog", headers=DE)
    assert client.get("/v1/catalog").json() == client.get("/v1/catalog", headers={"accept-language": "en"}).json()


def test_rule_messages_and_prices_are_german(client):
    body = {"model_id": I5, "options": [], "requirements": {"budget_max": 60000}}
    en = client.post("/v1/configurations/view", json=body).json()
    de = client.post("/v1/configurations/view", json=body, headers=DE).json()
    assert en["total_price"] == de["total_price"]
    assert "€71,900" in " ".join(u["message"] for u in en["unmet_requirements"])
    assert "71.900 €" in " ".join(u["message"] for u in de["unmet_requirements"])


def test_recommendation_reasons_are_german(client):
    req = {"requirements": {"powertrain_preferred": ["bev"], "child_seats": 3, "budget_max": 85000}}
    de = client.post("/v1/recommendations", json=req, headers=DE).json()
    text = " ".join(" ".join(e["reasons"]) for e in de["fits"] + de["near_misses"])
    assert text and not any(w in text for w in (" the ", " and ", " seats "))
