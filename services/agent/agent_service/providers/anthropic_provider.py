"""Anthropic Messages API adapter (Claude tool use)."""

from __future__ import annotations

import logging

import anthropic

from ..llm_agent import LLMStep, LLMUnavailable, ToolCall, ToolOutcome
from ..toolbox import TOOLS

log = logging.getLogger("agent.anthropic")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, system_prompt: str, effort: str | None = None, timeout_s: float = 60,
                 server_fallback: bool = True, client: anthropic.AsyncAnthropic | None = None):
        self.model = model
        self.effort = effort or "medium"
        self.server_fallback = server_fallback
        # The SDK reads ANTHROPIC_API_KEY from the environment; it is never passed or logged here.
        self.client = client or anthropic.AsyncAnthropic(timeout=timeout_s, max_retries=2)
        self.system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

    def user_message(self, text: str, state: str) -> dict:
        return {"role": "user", "content": [{"type": "text", "text": text}, {"type": "text", "text": state}]}

    def closing_message(self, text: str) -> dict:
        return {"role": "assistant", "content": [{"type": "text", "text": text}]}

    def tool_result_messages(self, outcomes: list[ToolOutcome]) -> list[dict]:
        blocks = []
        for o in outcomes:
            block = {"type": "tool_result", "tool_use_id": o.call.id, "content": o.content}
            if o.is_error:
                block["is_error"] = True
            blocks.append(block)
        return [{"role": "user", "content": blocks}]  # all results in one message

    async def complete(self, messages: list[dict]) -> LLMStep:
        kwargs: dict = dict(model=self.model, max_tokens=16000, system=self.system, tools=TOOLS,
                            messages=messages, output_config={"effort": self.effort})
        try:
            if self.server_fallback:
                # On a safety decline the API retries on a fallback model inside the same call.
                response = await self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                response = await self.client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable("rate limited") from exc
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("authentication failed - check ANTHROPIC_API_KEY") from exc
        except anthropic.BadRequestError as exc:
            log.error("bad request to Anthropic: %s", exc.message)
            raise LLMUnavailable("bad request") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("connection error") from exc

        if response.stop_reason == "refusal":
            raise LLMUnavailable("request declined")
        content = [block.model_dump(mode="json", exclude_none=True) for block in response.content]
        calls = [ToolCall(b.id, b.name, b.input or {}) for b in response.content if b.type == "tool_use"]
        stop = "continue" if response.stop_reason == "pause_turn" else (
            "tool_use" if response.stop_reason == "tool_use" and calls else "end")
        usage = response.usage
        return LLMStep(
            text="\n".join(b.text for b in response.content if b.type == "text").strip(),
            tool_calls=calls,
            stop=stop,
            assistant_messages=[{"role": "assistant", "content": content}],
            usage={"in": usage.input_tokens, "out": usage.output_tokens,
                   "cache_read": getattr(usage, "cache_read_input_tokens", None)},
        )
