"""End-to-end customer journey in guided (offline) mode, through the real catalog service."""

import pytest

REFERENCE = ("I need a family car for regular long-distance travel. I prefer electric, need room for three children, "
             "and do not want to spend more than EUR 85,000.")

pytestmark = pytest.mark.asyncio


def components(resp: dict, kind: str) -> list[dict]:
    return [c for c in resp["message"]["components"] if c["type"] == kind]


async def start(agent) -> str:
    r = await agent.post("/api/sessions")
    assert r.status_code == 201
    body = r.json()
    assert body["mode"] == "guided"
    assert components({"message": body["message"]}, "question")  # example prompts offered
    return body["session_id"]


async def say(agent, sid: str, message: str | None = None, action: dict | None = None) -> dict:
    payload = {"message": message} if message else {"action": action}
    r = await agent.post(f"/api/sessions/{sid}/turn", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


async def test_complete_journey_with_conflict_and_invalid_option(agent):
    sid = await start(agent)

    # 1. Natural language -> structured requirements -> explainable recommendations
    r = await say(agent, sid, REFERENCE)
    labels = [x["label"] for x in r["state"]["requirements"]]
    assert "Budget up to €85,000" in labels and "3 child seats" in labels and "Prefers electric" in labels
    assert r["state"]["assumptions"]
    cards = components(r, "model_cards")[0]["cards"]
    assert cards[0]["model_id"] == "i5_touring_edrive40"
    assert all(c["entry_price"] <= 85000 for c in cards)
    assert components(r, "tradeoffs")  # iX is €1,900 over budget -> offered as trade-off
    q = components(r, "question")
    assert len(q) == 1 and q[0]["topic"] == "towing"  # one focused, relevant question

    # 2. Answer via chip -> requirement updated, not asked again
    r = await say(agent, sid, action={"type": "answer", "value": "Bike carrier"})
    assert any(x["label"] == "Bike carrier" for x in r["state"]["requirements"])
    assert not [c for c in components(r, "question") if c["topic"] == "towing"]

    # 3. Select the recommended model -> required tow hitch added, suggestions shown
    r = await say(agent, sid, action={"type": "select_model", "model_id": "i5_touring_edrive40"})
    config = r["state"]["configuration"]
    assert config["model_id"] == "i5_touring_edrive40"
    assert "tow_hitch" in config["options"]
    toggles = components(r, "option_toggles")[0]["options"]
    assert any(o["id"] == "pkg_travel_comfort" for o in toggles)

    # 4. Dependency auto-added with explanation
    r = await say(agent, sid, action={"type": "change_option", "op": "add", "option_id": "pkg_driving_assistant_pro"})
    assert "Parking Assistant Plus" in r["message"]["text"]
    assert "pkg_parking_assistant" in r["state"]["configuration"]["options"]

    # 5. Conflict: package seats vs. sport seats -> explicit resolution, nothing changed silently
    await say(agent, sid, action={"type": "change_option", "op": "add", "option_id": "pkg_travel_comfort"})
    r = await say(agent, sid, "add the M Sport package")
    conflict = components(r, "conflict")[0]
    assert "Travel & Comfort Package" in conflict["message"]
    assert "pkg_travel_comfort" in r["state"]["configuration"]["options"]
    keep = conflict["resolutions"][-1]
    assert keep["change"] is None

    # 6. Invalid option for this model -> rejected with alternatives
    r = await say(agent, sid, "please add rear-seat entertainment")
    assert "not available" in r["message"]["text"]
    assert "rear_entertainment" not in r["state"]["configuration"]["options"]

    # 7. Graceful revision: lower the budget -> current config re-checked, savings suggested
    r = await say(agent, sid, "Actually, my budget is 78,000")
    assert "no longer fits" in r["message"]["text"]
    assert r["state"]["configuration"]["budget"]["over_by"] > 0

    # 8. Resolve by removing an option, then summary
    r = await say(agent, sid, action={"type": "change_option", "op": "remove", "option_id": "pkg_parking_assistant", "force": True})
    assert r["state"]["configuration"]["budget"]["over_by"] == 0
    r = await say(agent, sid, action={"type": "request_summary"})
    summary = components(r, "summary")[0]
    assert summary["valid"] and not summary["unmet_requirements"]
    assert summary["total_price"] <= 78000

    # Reload restores the transcript
    s = (await agent.get(f"/api/sessions/{sid}")).json()
    assert len(s["transcript"]) >= 10


async def test_unsatisfiable_requirements_offer_tradeoffs(agent):
    sid = await start(agent)
    r = await say(agent, sid, "We need 7 seats, must be electric, budget 80k")
    assert "No model meets all" in r["message"]["text"]
    trade = components(r, "tradeoffs")[0]["items"]
    assert trade
    # accept one trade-off -> requirements revised, recommendations recomputed
    r = await say(agent, sid, action={"type": "apply_tradeoff", "patch": trade[0]["patch"], "label": trade[0]["label"]})
    assert r["state"]["assumptions"][-1].startswith("Accepted trade-off")


async def test_remove_requirement_and_slider(agent):
    sid = await start(agent)
    await say(agent, sid, "sporty electric car around 60k")
    r = await say(agent, sid, action={"type": "set_preference", "key": "sportiness", "value": 0.1})
    assert any(x["field"] == "sportiness" and x["label"] == "Comfort-focused" for x in r["state"]["requirements"])
    r = await say(agent, sid, action={"type": "remove_requirement", "field": "budget_max"})
    assert not any(x["field"] == "budget_max" for x in r["state"]["requirements"])


async def test_compare_and_switch_model_keeps_compatible_options(agent):
    sid = await start(agent)
    await say(agent, sid, REFERENCE)
    r = await say(agent, sid, "compare the i5 and the X5")
    table = components(r, "comparison")[0]
    assert [m["model_id"] for m in table["models"]] == ["i5_touring_edrive40", "x5_xdrive50e"]
    await say(agent, sid, action={"type": "select_model", "model_id": "i5_touring_edrive40"})
    await say(agent, sid, action={"type": "change_option", "op": "add", "option_id": "hud"})
    r = await say(agent, sid, "let's switch to the X5 instead")
    assert r["state"]["configuration"]["model_id"] == "x5_xdrive50e"
    assert "hud" in r["state"]["configuration"]["options"]


async def test_api_errors(agent):
    assert (await agent.post("/api/sessions/nope/turn", json={"message": "hi"})).status_code == 404
    sid = await start(agent)
    assert (await agent.post(f"/api/sessions/{sid}/turn", json={})).status_code == 422
    bad = await agent.post(f"/api/sessions/{sid}/turn", json={"action": {"type": "set_preference", "key": "sportiness", "value": 7}})
    assert bad.status_code == 422
    r = await say(agent, sid, action={"type": "select_model", "model_id": "flying_car"})
    assert "Unknown model" in r["message"]["text"]
    r = await say(agent, sid, "blah")
    assert components(r, "question")  # guided recovery instead of a dead end


async def test_failed_turn_leaves_session_unchanged(catalog_client):
    """If the backend fails partway through a turn, nothing from that turn is kept."""
    import httpx

    from .conftest import catalog_app, make_client

    class FailingChanges(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.ASGITransport(app=catalog_app)

        async def handle_async_request(self, request):
            if request.url.path == "/v1/configurations/change":
                return httpx.Response(500, json={"detail": "boom"})
            return await self.inner.handle_async_request(request)

    from agent_service.catalog_client import CatalogClient
    flaky = CatalogClient("http://catalog", transport=FailingChanges(), retries=0)
    async with make_client(flaky) as client:
        sid = (await client.post("/api/sessions")).json()["session_id"]
        await client.post(f"/api/sessions/{sid}/turn", json={"message": "bike carrier, electric, budget 85,000"})
        r = await client.post(f"/api/sessions/{sid}/turn",
                              json={"action": {"type": "select_model", "model_id": "i5_touring_edrive40"}})
        assert r.status_code == 502  # selecting needs a change call (tow hitch), which fails
        state = (await client.get(f"/api/sessions/{sid}")).json()
        assert state["state"]["configuration"] is None  # model selection was rolled back
        assert any(x["label"] == "Bike carrier" for x in state["state"]["requirements"])  # earlier turn kept
