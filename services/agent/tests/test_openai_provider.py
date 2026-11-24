"""OpenAI provider: agent loop tested against a scripted fake Chat Completions API (no network, no API key)."""

from __future__ import annotations

import copy
import itertools
import json

import httpx
import openai
import pytest
from openai.types.chat import ChatCompletion

from .conftest import make_client

pytestmark = pytest.mark.asyncio
_ids = itertools.count()


def completion(content: str | None = None, tool_calls: list[dict] | None = None,
               finish_reason: str | None = None) -> ChatCompletion:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return ChatCompletion.model_validate({
        "id": f"chatcmpl_{next(_ids)}", "object": "chat.completion", "created": 0, "model": "gpt-5.5",
        "choices": [{"index": 0, "message": message,
                     "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop")}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })


def call(name: str, args: dict | str) -> dict:
    return {"id": f"call_{next(_ids)}", "type": "function",
            "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


class FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class FakeOpenAI:
    def __init__(self, script):
        self.completions = FakeCompletions(script)
        self.chat = self  # client.chat.completions.create


def tool_messages(kwargs: dict) -> list[dict]:
    return [m for m in kwargs["messages"] if m["role"] == "tool"]


async def turn(fake, catalog_client, payload: dict) -> dict:
    async with make_client(catalog_client, mode="llm", provider="openai", llm_client=fake) as client:
        sid = (await client.post("/api/sessions")).json()["session_id"]
        return (await client.post(f"/api/sessions/{sid}/turn", json=payload)).json()


async def test_function_calling_loop_produces_grounded_ui(catalog_client):
    fake = FakeOpenAI([
        completion(tool_calls=[
            call("update_requirements", {"patch": {"budget_max": 85000, "powertrain_preferred": ["bev"],
                                                   "child_seats": 3, "long_distance": True},
                                         "assumptions": ["Three children -> three child seats"]}),
            call("search_models", {})]),
        completion(tool_calls=[call("show_ui", {"components": [
            {"type": "model_cards", "model_ids": ["i5_touring_edrive40", "x5_xdrive50e"]},
            {"type": "question", "prompt": "Will you tow anything?", "choices": ["No", "Bike carrier"], "topic": "towing"}]})]),
        completion("The i5 Touring is the strongest fit."),
    ])
    r = await turn(fake, catalog_client, {"message": "family EV, 3 kids, 85k"})

    assert r["mode"] == "openai"
    assert r["message"]["text"] == "The i5 Touring is the strongest fit."
    assert [c["type"] for c in r["message"]["components"]] == ["model_cards", "question"]
    assert r["message"]["components"][0]["cards"][0]["entry_price"] == 71900  # from the catalog, not the model

    first = fake.completions.calls[0]
    assert first["model"] == "gpt-5.5"
    assert first["messages"][0]["role"] == "system"
    assert "<state>" in first["messages"][-1]["content"]
    assert {t["function"]["name"] for t in first["tools"]} >= {"update_requirements", "change_option", "show_ui"}
    assert "reasoning_effort" not in first  # only sent when LLM_EFFORT is configured
    second = fake.completions.calls[1]
    assert second["messages"][-3]["tool_calls"]  # assistant message with the calls precedes the results
    results = tool_messages(second)
    assert len(results) == 2 and not any(m["content"].startswith("ERROR") for m in results)


async def test_bad_arguments_are_returned_as_errors(catalog_client):
    fake = FakeOpenAI([
        completion(tool_calls=[call("show_ui", '{"components": [')]),  # truncated JSON
        completion(tool_calls=[call("select_model", {"model_id": "batmobile"})]),
        completion("Let me check the catalog."),
    ])
    r = await turn(fake, catalog_client, {"message": "hi"})
    assert r["message"]["components"] == []
    assert tool_messages(fake.completions.calls[1])[0]["content"].startswith("ERROR: Invalid JSON")
    assert tool_messages(fake.completions.calls[2])[-1]["content"].startswith("ERROR")


async def test_outage_falls_back_to_guided_mode(catalog_client):
    outage = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    r = await turn(FakeOpenAI([outage]), catalog_client, {"message": "family car, electric, three children, budget 85,000"})
    assert r["mode"] == "guided"
    types = [c["type"] for c in r["message"]["components"]]
    assert types[0] == "notice" and "model_cards" in types


async def test_content_filter_falls_back(catalog_client):
    r = await turn(FakeOpenAI([completion("", finish_reason="content_filter")]), catalog_client,
                   {"message": "electric car under 60k"})
    assert r["mode"] == "guided"


async def test_history_stays_valid_across_turns(catalog_client):
    fake = FakeOpenAI([
        completion(tool_calls=[call("select_model", {"model_id": "i5_touring_edrive40"})]),
        completion("Configuring the i5."),
        completion("Sure."),
    ])
    async with make_client(catalog_client, mode="llm", provider="openai", llm_client=fake) as client:
        sid = (await client.post("/api/sessions")).json()["session_id"]
        await client.post(f"/api/sessions/{sid}/turn", json={"message": "configure the i5"})
        r = (await client.post(f"/api/sessions/{sid}/turn", json={"message": "thanks"})).json()
    assert r["state"]["configuration"]["model_id"] == "i5_touring_edrive40"
    roles = [m["role"] for m in fake.completions.calls[2]["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "user"]
