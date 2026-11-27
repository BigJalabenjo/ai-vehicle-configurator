"""German sessions: greeting, guided replies, catalog texts, German input and the voice language."""

import pytest

from agent_service import i18n
from agent_service.nlu import parse
from agent_service.offline_agent import TEXT

from .test_voice import WAV, FakeSpeechAPI, client


async def turn(c, sid, **payload) -> dict:
    r = await c.post(f"/api/sessions/{sid}/turn", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_german_session_greets_and_answers_in_german(agent):
    r = await agent.post("/api/sessions", json={"language": "de"})
    body = r.json()
    assert body["state"]["language"] == "de"
    assert body["message"]["text"].startswith("Hallo!")
    sid = body["session_id"]
    reply = await turn(agent, sid, message="Familienauto, elektrisch, drei Kinder, höchstens 85.000 €")
    text = reply["message"]["text"]
    assert "Das habe ich verstanden" in text and "85.000 €" in text
    labels = [r["label"] for r in reply["state"]["requirements"]]
    assert "3 Kindersitze" in labels


@pytest.mark.asyncio
async def test_switching_language_redoes_an_untouched_greeting(agent):
    sid = (await agent.post("/api/sessions")).json()["session_id"]
    res = await turn(agent, sid, action={"type": "set_language", "language": "de"})
    assert res["message"] is None and res["feedback"]["kind"] == "language"
    session = (await agent.get(f"/api/sessions/{sid}")).json()
    assert session["state"]["language"] == "de"
    assert [m["text"][:6] for m in session["transcript"]] == ["Hallo!"]


@pytest.mark.asyncio
async def test_switching_mid_conversation_keeps_history_and_changes_new_replies(agent):
    sid = (await agent.post("/api/sessions")).json()["session_id"]
    await turn(agent, sid, message="electric family car, budget 85k")
    await turn(agent, sid, action={"type": "set_language", "language": "de"})
    session = (await agent.get(f"/api/sessions/{sid}")).json()
    assert session["transcript"][0]["text"].startswith("Hi!")  # earlier messages stay as they were
    reply = await turn(agent, sid, message="Wir brauchen 7 Sitze")
    assert "Alles klar" in reply["message"]["text"] or "Kein Modell" in reply["message"]["text"]


@pytest.mark.asyncio
async def test_unknown_language_is_rejected(agent):
    sid = (await agent.post("/api/sessions")).json()["session_id"]
    r = await agent.post(f"/api/sessions/{sid}/turn", json={"action": {"type": "set_language", "language": "fr"}})
    assert r.status_code == 422


@pytest.mark.parametrize("text, expected", [
    ("Wir sind eine Familie mit drei Kindern", {"child_seats": 3}),
    ("Budget bis 70 tausend Euro", {"budget_max": 70000}),
    ("Wir ziehen einen Wohnwagen", {"towing_kg": 1500}),
    ("Am liebsten elektrisch", {"powertrain_preferred": ["bev"]}),
    ("Wir brauchen sieben Sitze", {"min_seats": 7}),
])
def test_german_input_is_understood(text, expected):
    patch = parse(text).patch
    assert {k: patch.get(k) for k in expected} == expected


@pytest.mark.parametrize("language", ["en", "de"])
def test_every_guided_choice_is_understood(language):
    i18n.use(language)
    try:
        for key in ("q_budget", "q_people", "q_towing"):
            for choice in TEXT[language][key][1]:
                assert parse(choice).patch, f"{language}: {choice!r}"
    finally:
        i18n.use("en")


def test_guided_texts_exist_in_both_languages():
    assert TEXT["en"].keys() == TEXT["de"].keys()


@pytest.mark.asyncio
async def test_voice_listens_and_speaks_in_the_session_language(catalog_client):
    fake = FakeSpeechAPI()
    async with client(catalog_client, fake) as c:
        sid = (await c.post("/api/sessions", json={"language": "de"})).json()["session_id"]
        await c.post(f"/api/sessions/{sid}/voice/transcribe", content=WAV, headers={"content-type": "audio/wav"})
        await c.post(f"/api/sessions/{sid}/voice/speech", json={"text": "Gute Wahl."})
        assert fake.transcribed[-1]["language"] == "de"
        assert "Hochdeutsch" in fake.spoken[-1]["instructions"]

        await turn(c, sid, action={"type": "set_language", "language": "en"})
        await c.post(f"/api/sessions/{sid}/voice/speech", json={"text": "Great choice."})
        assert "Speak English" in fake.spoken[-1]["instructions"]
