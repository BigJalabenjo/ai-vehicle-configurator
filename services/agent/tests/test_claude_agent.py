"""Claude-mode orchestration tested against a scripted fake Messages API (no network, no API key)."""

from __future__ import annotations

import copy
import itertools

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from .conftest import make_client

pytestmark = pytest.mark.asyncio
_ids = itertools.count()


def message(content: list[dict], stop_reason: str) -> BetaMessage:
    return BetaMessage.model_validate({
        "id": f"msg_{next(_ids)}", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })


def tool(name: str, input_: dict) -> dict:
    return {"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": input_}


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))  # the agent keeps mutating its message list
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class FakeAnthropic:
    def __init__(self, script):
        self.messages = FakeMessages(script)
        self.beta = self  # client.beta.messages.create -> same fake


def tool_results(call: dict) -> list[dict]:
    last = call["messages"][-1]
    return [b for b in last["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


async def start(client) -> str:
    return (await client.post("/api/sessions")).json()["session_id"]


async def test_tool_loop_produces_grounded_ui(catalog_client):
    fake = FakeAnthropic([
        message([tool("update_requirements", {
            "patch": {"budget_max": 85000, "powertrain_preferred": ["bev"], "child_seats": 3, "long_distance": True},
            "assumptions": ["Three children -> three child seats"]}),
            tool("search_models", {})], "tool_use"),
        message([tool("show_ui", {"components": [
            {"type": "model_cards", "model_ids": ["i5_touring_edrive40", "x5_xdrive50e"]},
            {"type": "question", "prompt": "Will you tow anything?", "choices": ["No", "Bike carrier"], "topic": "towing"}]})],
            "tool_use"),
        message([{"type": "text", "text": "The i5 Touring is the strongest fit."}], "end_turn"),
    ])
    async with make_client(catalog_client, mode="claude", claude_client=fake) as client:
        sid = await start(client)
        r = (await client.post(f"/api/sessions/{sid}/turn", json={"message": "family EV, 3 kids, 85k"})).json()

    assert r["mode"] == "claude"
    assert r["message"]["text"] == "The i5 Touring is the strongest fit."
    types = [c["type"] for c in r["message"]["components"]]
    assert types == ["model_cards", "question"]
    card = r["message"]["components"][0]["cards"][0]
    assert card["entry_price"] == 71900  # price comes from the catalog, not the model
    assert "Three children -> three child seats" in r["state"]["assumptions"]

    first = fake.messages.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default" and first["betas"]
    assert {t["name"] for t in first["tools"]} >= {"update_requirements", "change_option", "show_ui"}
    assert "<state>" in first["messages"][-1]["content"][1]["text"]
    results = tool_results(fake.messages.calls[1])
    assert len(results) == 2 and not any(r.get("is_error") for r in results)


async def test_invalid_tool_input_is_returned_as_error_for_self_correction(catalog_client):
    fake = FakeAnthropic([
        message([tool("show_ui", {"components": [{"type": "model_cards", "model_ids": ["batmobile"]}]})], "tool_use"),
        message([tool("update_requirements", {"patch": {"budget_max": -1}})], "tool_use"),
        message([{"type": "text", "text": "Sorry - let me check the catalog."}], "end_turn"),
    ])
    async with make_client(catalog_client, mode="claude", claude_client=fake) as client:
        sid = await start(client)
        r = (await client.post(f"/api/sessions/{sid}/turn", json={"message": "hi"})).json()
    assert r["message"]["components"] == []
    assert tool_results(fake.messages.calls[1])[0]["is_error"] is True
    assert tool_results(fake.messages.calls[2])[0]["is_error"] is True


async def test_conflict_from_tool_is_rendered_automatically(catalog_client):
    fake = FakeAnthropic([
        message([tool("select_model", {"model_id": "i5_touring_edrive40"})], "tool_use"),
        message([tool("change_option", {"action": "add", "option_id": "pkg_travel_comfort"}),
                 tool("change_option", {"action": "add", "option_id": "seats_sport"})], "tool_use"),
        message([{"type": "text", "text": "Sport seats would break the Travel & Comfort Package."}], "end_turn"),
    ])
    async with make_client(catalog_client, mode="claude", claude_client=fake) as client:
        sid = await start(client)
        r = (await client.post(f"/api/sessions/{sid}/turn", json={"message": "i5 with travel package and sport seats"})).json()
    assert [c["type"] for c in r["message"]["components"]] == ["conflict"]
    assert "pkg_travel_comfort" in r["state"]["configuration"]["options"]


async def test_llm_outage_falls_back_to_guided_mode(catalog_client):
    outage = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    fake = FakeAnthropic([outage])
    async with make_client(catalog_client, mode="claude", claude_client=fake) as client:
        sid = await start(client)
        r = (await client.post(f"/api/sessions/{sid}/turn", json={
            "message": "family car, electric, three children, budget 85,000"})).json()
    assert r["mode"] == "guided"
    types = [c["type"] for c in r["message"]["components"]]
    assert types[0] == "notice" and "model_cards" in types


async def test_refusal_falls_back(catalog_client):
    fake = FakeAnthropic([message([], "refusal")])
    async with make_client(catalog_client, mode="claude", claude_client=fake) as client:
        sid = await start(client)
        r = (await client.post(f"/api/sessions/{sid}/turn", json={"message": "electric car under 60k"})).json()
    assert r["mode"] == "guided"


async def test_ui_action_is_applied_before_llm_narrates(catalog_client):
    fake = FakeAnthropic([message([{"type": "text", "text": "Nice pick!"}], "end_turn")])
    async with make_client(catalog_client, mode="claude", claude_client=fake) as client:
        sid = await start(client)
        r = (await client.post(f"/api/sessions/{sid}/turn",
                               json={"action": {"type": "select_model", "model_id": "ix_xdrive45"}})).json()
    assert r["state"]["configuration"]["model_id"] == "ix_xdrive45"
    assert fake.messages.calls[0]["messages"][-1]["content"][0]["text"].startswith("[UI]")
