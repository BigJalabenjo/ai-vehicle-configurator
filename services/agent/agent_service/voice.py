"""Voice mode: speech-to-text for what the customer says, text-to-speech for the assistant's replies.

Turn-based on purpose (not a realtime voice model): the recognised text goes through the normal
turn endpoint, so the same agent, tools and rules engine answer, and the transcript stays text.
Listening, end-of-speech detection and barge-in happen in the browser (see web/voice.js); this
module only converts audio to text and text to audio. Audio and text are never logged.
"""

from __future__ import annotations

import logging
import re

import openai

from . import i18n
from .config import Settings

log = logging.getLogger("agent.voice")

# Browsers record in different containers; these are the ones the transcription API accepts.
AUDIO_TYPES = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/webm": "webm", "audio/ogg": "ogg",
               "audio/mp4": "mp4", "audio/mpeg": "mp3"}

TTS_INSTRUCTIONS = {
    "en": "You are a friendly, calm product advisor in a car configurator. Speak English naturally and at a relaxed "
          "pace. Read prices as amounts in euros.",
    "de": "Du bist ein freundlicher, ruhiger Produktberater in einem Autokonfigurator. Sprich natürliches "
          "Hochdeutsch in entspanntem Tempo. Lies Preise als Euro-Beträge vor, z. B. 71.900 € als "
          "„einundsiebzigtausendneunhundert Euro“. Modellnamen wie iX1 xDrive30 sprichst du so aus, wie es im deutschen Autohandel üblich ist.",
}
class VoiceUnavailable(RuntimeError):
    """The speech service could not be reached or refused the request."""


# No transcription prompt on purpose: given one, the model returns it (or invents a configurator-
# style sentence) for recordings without words, such as a cough or typing. Without it, such
# recordings come back empty, and model names are put right afterwards (correct_names).
#
# Stock phrases the model may still produce for non-speech (learned from subtitled videos):
NON_SPEECH = {
    "thank you", "thanks for watching", "thank you for watching", "you", "bye",
    "vielen dank", "danke fürs zuschauen", "vielen dank fürs zuschauen", "tschüss",
    "untertitel im auftrag des zdf", "untertitelung des zdf", "untertitel der amara org community",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[\wäöüß]+", text.lower())


def is_filler(text: str) -> bool:
    return " ".join(_words(text)) in NON_SPEECH


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _close(a: str, b: str) -> bool:
    """Equal, or one letter wrong/missing (the classic edit distance, capped at 1)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or len(b) < 6:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i:] == b[i + 1:] or a[i + 1:] == b[i:]


def correct_names(text: str, model_names: list[str]) -> str:
    """Write model names the catalog way: 'IX1 X Drive 30' -> 'iX1 xDrive30', 'e4 eDrive 40' -> 'i4 eDrive40'."""
    targets: dict[str, str] = {}
    for name in model_names:
        short = name.removeprefix("BMW ")
        for variant in (short, " ".join(short.split()[:2]), short.split()[0]):  # full, first two words, model code
            targets.setdefault(_compact(variant), variant)
    tokens = text.split(" ")
    out, i = [], 0
    while i < len(tokens):
        for size in range(min(5, len(tokens) - i), 0, -1):
            window = " ".join(tokens[i:i + size])
            core = window.rstrip(".,!?;:")
            key = _compact(core)
            if not any(ch.isdigit() for ch in key):
                continue
            hit = next((v for k, v in targets.items() if _close(key, k)), None)
            if hit:
                out.append(hit + window[len(core):])
                i += size
                break
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out)


def speakable(text: str) -> str:
    """Strip the little markdown replies use, so it isn't read out."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


class VoiceService:
    def __init__(self, cfg: Settings, client=None):
        self.cfg = cfg
        self._client = client  # injectable SDK client (tests)

    @property
    def enabled(self) -> bool:
        return self.cfg.voice_setting and (self._client is not None or self.cfg.voice_enabled)

    @property
    def client(self):
        if self._client is None:
            # The SDK reads OPENAI_API_KEY from the environment; it is never passed or logged here.
            self._client = openai.AsyncOpenAI(timeout=30, max_retries=1)
        return self._client

    async def transcribe(self, audio: bytes, content_type: str, language: str = "en",
                         model_names: list[str] | None = None) -> str:
        ext = AUDIO_TYPES[content_type]
        try:
            # The language hint keeps short German answers ("Ja, bitte") from being heard as English.
            result = await self.client.audio.transcriptions.create(
                model=self.cfg.voice_stt_model, file=(f"speech.{ext}", audio, content_type), language=language)
        except openai.OpenAIError as exc:
            log.warning("transcription failed: %s", type(exc).__name__)
            raise VoiceUnavailable(i18n.t("voice_stt_down")) from exc
        text = (result.text or "").strip()
        if is_filler(text):
            log.info("dropped a transcript without speech (%d chars)", len(text))  # never the text itself
            return ""
        return correct_names(text, model_names or [])

    async def speak(self, text: str, language: str = "en") -> bytes:
        try:
            response = await self.client.audio.speech.create(
                model=self.cfg.voice_tts_model, voice=self.cfg.voice_tts_voice, input=speakable(text),
                instructions=TTS_INSTRUCTIONS.get(language, TTS_INSTRUCTIONS["en"]), response_format="mp3")
        except openai.OpenAIError as exc:
            log.warning("speech synthesis failed: %s", type(exc).__name__)
            raise VoiceUnavailable(i18n.t("voice_tts_down")) from exc
        return response.content
