"""Voice endpoints: speech-to-text and text-to-speech through a fake OpenAI client (no network, no key)."""

from types import SimpleNamespace

import httpx
import openai
import pytest

from agent_service.config import Settings
from agent_service.main import Runtime, create_app
from agent_service.voice import correct_names, is_filler, speakable

pytestmark = pytest.mark.asyncio

WAV = b"RIFF" + b"\x00" * 60


class FakeSpeechAPI:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.transcribed: list[dict] = []
        self.spoken: list[dict] = []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._transcribe),
                                     speech=SimpleNamespace(create=self._speak))

    def _error(self):
        return openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))

    async def _transcribe(self, **kwargs):
        if self.fail:
            raise self._error()
        self.transcribed.append(kwargs)
        return SimpleNamespace(text="  I need an electric car for my family.  ")

    async def _speak(self, **kwargs):
        if self.fail:
            raise self._error()
        self.spoken.append(kwargs)
        return SimpleNamespace(content=b"ID3-fake-mp3")


def client(catalog_client, fake=None, **cfg) -> httpx.AsyncClient:
    settings = Settings(agent_mode="offline", **cfg)  # type: ignore[arg-type]
    app = create_app(Runtime(catalog=catalog_client, cfg=settings, voice_client=fake))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent")


async def new_session(c) -> dict:
    r = await c.post("/api/sessions")
    assert r.status_code == 201
    return r.json()


async def test_session_says_whether_voice_is_available(catalog_client):
    async with client(catalog_client, FakeSpeechAPI()) as c:
        assert (await new_session(c))["voice"] is True
    async with client(catalog_client, FakeSpeechAPI(), voice_setting=False) as c:
        body = await new_session(c)
        assert body["voice"] is False
        assert (await c.get(f"/api/sessions/{body['session_id']}")).json()["voice"] is False


async def test_transcribes_a_recording_without_a_prompt(catalog_client):
    fake = FakeSpeechAPI()
    async with client(catalog_client, fake) as c:
        sid = (await new_session(c))["session_id"]
        r = await c.post(f"/api/sessions/{sid}/voice/transcribe", content=WAV, headers={"content-type": "audio/wav"})
    assert r.status_code == 200
    assert r.json() == {"text": "I need an electric car for my family."}
    call = fake.transcribed[0]
    assert call["model"] == "gpt-4o-mini-transcribe"
    assert call["file"] == ("speech.wav", WAV, "audio/wav")
    assert "prompt" not in call  # a prompt gets read back for recordings without speech


async def test_rejects_bad_recordings(catalog_client):
    async with client(catalog_client, FakeSpeechAPI(), voice_max_audio_bytes=100) as c:
        sid = (await new_session(c))["session_id"]
        url = f"/api/sessions/{sid}/voice/transcribe"
        assert (await c.post(url, content=WAV, headers={"content-type": "text/plain"})).status_code == 415
        assert (await c.post(url, content=b"", headers={"content-type": "audio/wav"})).status_code == 422
        assert (await c.post(url, content=b"x" * 101, headers={"content-type": "audio/wav"})).status_code == 413


async def test_voice_needs_a_session_and_the_feature(catalog_client):
    async with client(catalog_client, FakeSpeechAPI()) as c:
        r = await c.post("/api/sessions/nope/voice/speech", json={"text": "Hi"})
        assert r.status_code == 404
    async with client(catalog_client, FakeSpeechAPI(), voice_setting=False) as c:
        sid = (await new_session(c))["session_id"]
        r = await c.post(f"/api/sessions/{sid}/voice/speech", json={"text": "Hi"})
        assert r.status_code == 404
        assert r.json()["detail"] == "Voice is not enabled"


async def test_reads_a_reply_aloud(catalog_client):
    fake = FakeSpeechAPI()
    async with client(catalog_client, fake) as c:
        sid = (await new_session(c))["session_id"]
        r = await c.post(f"/api/sessions/{sid}/voice/speech", json={"text": "The **iX1** starts at €55,400."})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3-fake-mp3"
    call = fake.spoken[0]
    assert call["input"] == "The iX1 starts at €55,400."  # markdown is not read out
    assert (call["model"], call["voice"], call["response_format"]) == ("gpt-4o-mini-tts", "marin", "mp3")


async def test_rejects_empty_or_long_speech(catalog_client):
    async with client(catalog_client, FakeSpeechAPI(), voice_max_speech_chars=20) as c:
        sid = (await new_session(c))["session_id"]
        url = f"/api/sessions/{sid}/voice/speech"
        assert (await c.post(url, json={"text": "   "})).status_code == 422
        assert (await c.post(url, json={"text": "x" * 21})).status_code == 413


async def test_speech_service_outage_is_a_clear_error(catalog_client):
    async with client(catalog_client, FakeSpeechAPI(fail=True)) as c:
        sid = (await new_session(c))["session_id"]
        r = await c.post(f"/api/sessions/{sid}/voice/transcribe", content=WAV, headers={"content-type": "audio/wav"})
        assert (r.status_code, r.json()["detail"]) == (502, "Speech recognition is unavailable right now.")
        r = await c.post(f"/api/sessions/{sid}/voice/speech", json={"text": "Hello"})
        assert (r.status_code, r.json()["detail"]) == (502, "Speech output is unavailable right now.")


async def test_speakable_strips_markdown():
    assert speakable("**Great choice!**\n- Heated seats\n- HUD") == "Great choice! Heated seats HUD"


MODELS = ["BMW i4 eDrive40 Gran Coupé", "BMW i5 Touring eDrive40", "BMW iX1 xDrive30", "BMW iX xDrive45",
          "BMW X5 xDrive50e", "BMW X7 xDrive40d", "BMW 225e xDrive Active Tourer", "BMW 520d Touring"]


@pytest.mark.parametrize("heard, written", [
    ("Ich nehme den IX1 X Drive 30.", "Ich nehme den iX1 xDrive30."),
    ("Den e4 eDrive 40 Gran Coupé bitte.", "Den i4 eDrive40 Gran Coupé bitte."),
    ("Lieber, der X5 xDrive50e mit Harman Kardon Sound.", "Lieber, der X5 xDrive50e mit Harman Kardon Sound."),
    ("What about the ix x drive 45?", "What about the iX xDrive45?"),
    ("Compare the I5 and the x7", "Compare the i5 and the X7"),
    ("Budget 60 000 Euro, 3 Kinder", "Budget 60 000 Euro, 3 Kinder"),
    ("Ja, bitte.", "Ja, bitte."),
])
async def test_model_names_are_written_the_catalog_way(heard, written):
    assert correct_names(heard, MODELS) == written


@pytest.mark.parametrize("text, filler", [
    ("Vielen Dank fürs Zuschauen!", True), ("Thank you.", True), ("Untertitel im Auftrag des ZDF", True),
    ("Danke, das passt so", False), ("Danke", False), ("Thank you, that works", False),
])
async def test_stock_phrases_for_non_speech_are_dropped(text, filler):
    assert is_filler(text) is filler


async def test_filler_and_names_are_handled_on_the_endpoint(catalog_client):
    fake = FakeSpeechAPI()
    heard = iter(["Vielen Dank fürs Zuschauen.", "Ich nehme den IX1 X Drive 30."])

    async def transcribe(**kwargs):
        return SimpleNamespace(text=next(heard))
    fake.audio.transcriptions.create = transcribe
    async with client(catalog_client, fake) as c:
        sid = (await new_session(c))["session_id"]
        url = f"/api/sessions/{sid}/voice/transcribe"
        assert (await c.post(url, content=WAV, headers={"content-type": "audio/wav"})).json()["text"] == ""
        assert (await c.post(url, content=WAV, headers={"content-type": "audio/wav"})).json()["text"] == \
            "Ich nehme den iX1 xDrive30."
