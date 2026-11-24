"""Claude-powered configurator agent (Messages API, manual tool loop).

We own the loop (rather than a hosted agent runtime) because every tool call
must go through our own rules engine, the loop needs a hard step limit, and
the conversation state lives in our session store.
"""

from __future__ import annotations

import json
import logging
import time

import anthropic

from .config import Settings
from .toolbox import TOOLS, Toolbox, ToolError

log = logging.getLogger("agent.claude")

FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_TEMPLATE = """You are the vehicle configuration assistant of a car brand's online configurator. You help a customer \
go from a description of their needs to a valid, explainable vehicle configuration.

How to work:
- Translate what the customer says into structured requirements with update_requirements. Distinguish soft \
preferences ("I prefer electric" -> powertrain_preferred) from hard constraints ("must be electric" -> \
powertrain_required). Record each interpretation you make as an assumption so the customer can correct it.
- Then call search_models and present the best matches with show_ui (model_cards). If nothing fits, explain the \
conflict plainly and offer the trade-offs (show_ui tradeoffs) - never pretend a model fits.
- Ask only questions whose answer would change the recommendation or configuration, at most one question per turn, \
using show_ui 'question' with short answer choices (or 'preference_slider' for comfort vs. sportiness). Do not ask \
about topics listed in <state> as already asked. Never ask for personal data (name, address, phone, e-mail).
- When the customer picks a model, call select_model, then suggest a few options that fit their needs \
(show_ui option_toggles).
- Option changes go through change_option. If it returns a conflict or error, explain it in one or two sentences; \
the UI already shows the resolution buttons. Use force=true only after the customer explicitly chose to accept the \
resolution.
- When requirements change, update them, re-check the current configuration (unmet_requirements, budget), and \
re-run search_models if the selected model no longer fits.
- When the customer is done, show_ui 'summary'.

Rules:
- Every price, spec, availability or compatibility statement must come from a tool result in this conversation. \
Never estimate or invent numbers. Use EUR formatted like "€71,900".
- Messages starting with [UI] describe actions the customer took in the interface; they have already been applied. \
React to them; do not repeat them.
- Keep replies short and friendly: at most 3 short paragraphs or ~90 words. The UI carries the detail.
- Reply in the customer's language.

Catalog overview (ids for tool calls):
{catalog}
"""


def build_catalog_overview(catalog: dict) -> str:
    models = "\n".join(f"- {m['id']}: {m['name']} ({m['powertrain']}, {m['body']}, from €{m['base_price']:,})"
                       for m in catalog["models"])
    options = "\n".join(f"- {o['id']}: {o['name']} ({o['category']})" for o in catalog["options"])
    return f"Models:\n{models}\nOptions:\n{options}\n{catalog['disclaimer']}"


def state_block(toolbox: Toolbox) -> str:
    st = toolbox.state
    data = {
        "requirements": st.requirements.model_dump(exclude_defaults=True),
        "assumptions": st.assumptions,
        "selected_model": st.model_id,
        "selected_options": st.options,
        "already_asked": sorted(set(st.asked)),
        "ui_events_since_last_turn": st.ui_events,
    }
    return f"<state>{json.dumps(data)}</state>"


class LLMUnavailable(RuntimeError):
    """Claude could not be reached or refused; the orchestrator falls back to guided mode."""


class ClaudeAgent:
    def __init__(self, settings: Settings, catalog_overview: str, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self.client = client or anthropic.AsyncAnthropic(timeout=settings.llm_timeout_s, max_retries=2)
        self.system = [{"type": "text", "text": SYSTEM_TEMPLATE.format(catalog=catalog_overview),
                        "cache_control": {"type": "ephemeral"}}]

    async def _create(self, messages: list[dict]):
        kwargs: dict = dict(
            model=self.settings.llm_model,
            max_tokens=16000,
            system=self.system,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": self.settings.llm_effort},
        )
        if self.settings.llm_server_fallback:
            # On a safety decline the API retries on a fallback model inside the same call.
            return await self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return await self.client.messages.create(**kwargs)

    async def run(self, toolbox: Toolbox, user_text: str) -> str:
        state = toolbox.state
        messages: list[dict] = list(state.llm_history)
        messages.append({"role": "user", "content": [
            {"type": "text", "text": user_text},
            {"type": "text", "text": state_block(toolbox)},
        ]})
        final_text = ""
        for step in range(self.settings.llm_max_steps):
            started = time.perf_counter()
            try:
                response = await self._create(messages)
            except anthropic.RateLimitError as exc:
                raise LLMUnavailable("rate limited") from exc
            except anthropic.AuthenticationError as exc:
                raise LLMUnavailable("authentication failed - check ANTHROPIC_API_KEY") from exc
            except anthropic.BadRequestError as exc:
                log.error("bad request to Claude: %s", exc.message)
                raise LLMUnavailable("bad request") from exc
            except anthropic.APIStatusError as exc:
                raise LLMUnavailable(f"API error {exc.status_code}") from exc
            except anthropic.APIConnectionError as exc:
                raise LLMUnavailable("connection error") from exc
            usage = response.usage
            log.info("claude step=%d stop=%s in=%s out=%s cache_read=%s latency_ms=%.0f", step, response.stop_reason,
                     usage.input_tokens, usage.output_tokens, getattr(usage, "cache_read_input_tokens", None),
                     (time.perf_counter() - started) * 1000)

            if response.stop_reason == "refusal":
                raise LLMUnavailable("request declined")

            content = [block.model_dump(mode="json", exclude_none=True) for block in response.content]
            messages.append({"role": "assistant", "content": content})
            text = "\n".join(b.text for b in response.content if b.type == "text").strip()
            if text:
                final_text = text
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use" or not tool_uses:
                break

            results = []
            for block in tool_uses:
                try:
                    result = await toolbox.execute(block.name, block.input or {})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})
                except ToolError as exc:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True})
            messages.append({"role": "user", "content": results})
        else:
            final_text = final_text or "I've prepared what I could - let me know how you'd like to continue."
            # Close the dangling tool_use so the history stays valid for the next turn.
            if messages[-1]["role"] == "user":
                messages.append({"role": "assistant", "content": [{"type": "text", "text": final_text}]})

        state.llm_history = messages
        state.ui_events = []
        return final_text
