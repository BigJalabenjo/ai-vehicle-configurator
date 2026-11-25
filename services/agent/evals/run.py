"""Tiny LLM evaluation: plays a few scripted customer conversations against the *real* model and checks
the outcome with rules (no AI grader), so one run costs only a few cents.

    make eval                      # from the repository root; reads OPENAI_API_KEY from .env
    LLM_MODEL=gpt-5.4 make eval    # compare another model

What is checked per case (see cases.json): extracted needs, chosen model, cards shown, conflicts surfaced,
validity of the final configuration (from the rules engine), and - for every reply - that each euro amount
in the text exists in the catalog, the response data or the customer's own words (no invented prices).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "services" / "catalog"))

# Rough list prices in USD per million tokens (input, output), for the cost line only.
PRICES = {"gpt-5.5": (5.0, 30.0), "gpt-5.4": (2.5, 15.0)}


def load_env_file() -> None:
    """Take the API key and model settings from the repository's .env, unless already set."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in {"OPENAI_API_KEY", "LLM_MODEL", "LLM_EFFORT"} and value.strip() and not os.getenv(key):
            os.environ[key] = value.strip().strip('"').strip("'")


class UsageLog(logging.Handler):
    """Collects token usage from the agent's own per-call log line."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "agent.llm" and record.msg.startswith("llm provider") and isinstance(record.args, tuple):
            self.calls.append(record.args[4] or {})


def numbers_in(obj) -> set[int]:
    """Every integer that appears anywhere in a JSON-like structure (values and inside strings)."""
    out: set[int] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(round(obj))
    elif isinstance(obj, str):
        out |= {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", obj)}
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= numbers_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= numbers_in(v)
    return out


EURO = re.compile(r"(?:€\s?|EUR\s?)(\d[\d,.]*)|(\d[\d,.]*)\s?(?:€|EUR|euros?)", re.I)


def euro_amounts(text: str) -> list[int]:
    amounts = []
    for a, b in EURO.findall(text):
        raw = (a or b).rstrip(".,")
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):  # 85,000 or 85.000
            raw = re.sub(r"[.,]", "", raw)
        try:
            amounts.append(round(float(raw.replace(",", ""))))
        except ValueError:
            pass
    return amounts


def component_summary(c: dict) -> dict:
    """What the viewer needs to show a card the AI chose, without the full payload."""
    out: dict = {"type": c["type"]}
    if c["type"] == "model_cards":
        out["title"] = c.get("title", "")
        out["items"] = [{"name": x["name"], "price": x["entry_price"], "fits": x["fits"]} for x in c["cards"]]
    elif c["type"] == "question":
        out["text"] = c.get("prompt", "")
        out["items"] = [ch.get("label", "") for ch in c.get("choices", [])]
    elif c["type"] in ("conflict", "notice"):
        out["text"] = c.get("message") or c.get("text", "")
    elif c["type"] == "tradeoffs":
        out["items"] = [t["label"] for t in c["items"]]
    elif c["type"] == "option_toggles":
        out["title"] = c.get("title", "")
        out["items"] = [o.get("name", "") for o in c["options"]]
    elif c["type"] == "comparison":
        out["items"] = [m["name"] for m in c["models"]]
    return out


def final_summary(state: dict) -> dict:
    v = state["configuration"]
    return {"needs": [r["label"] for r in state["requirements"]],
            "model": v and v["model_name"], "total_price": v and v["total_price"], "valid": v and v["valid"],
            "options": v and [o["name"] for o in v["catalog_options"] if o["state"] in ("selected", "included")]}


async def run_case(client: httpx.AsyncClient, case: dict, catalog_numbers: set[int], transcript: list[dict]) -> list[tuple[str, bool, str]]:
    sid = (await client.post("/api/sessions")).json()["session_id"]
    replies: list[dict] = []
    for text in case["messages"]:
        transcript.append({"role": "user", "text": text})
        t0 = time.perf_counter()
        r = await client.post(f"/api/sessions/{sid}/turn", json={"message": text}, timeout=180)
        r.raise_for_status()
        replies.append(r.json())
        transcript.append({"role": "assistant", "text": replies[-1]["message"]["text"], "mode": replies[-1]["mode"],
                           "seconds": round(time.perf_counter() - t0, 1),
                           "components": [component_summary(c) for c in replies[-1]["message"]["components"]]})
    last, state, exp = replies[-1], replies[-1]["state"], case["expect"]
    LAST_STATE[case["id"]] = final_summary(state)
    values, config = state["requirement_values"], state["configuration"]
    last_types = [c["type"] for c in last["message"]["components"]]
    checks: list[tuple[str, bool, str]] = []

    for key, want in exp.get("requirements", {}).items():
        checks.append((f"need {key} = {want}", values.get(key) == want, f"got {values.get(key)!r}"))
    if pt := exp.get("powertrain_includes"):
        got = values["powertrain_required"] + values["powertrain_preferred"]
        checks.append((f"powertrain includes {pt}", pt in got, f"got {got}"))
    for t in exp.get("components_in_last_reply", []):
        checks.append((f"shows {t}", t in last_types, f"shown: {last_types}"))
    if any_of := exp.get("components_in_last_reply_any"):
        checks.append((f"shows one of {any_of}", bool(set(any_of) & set(last_types)), f"shown: {last_types}"))
    if exp.get("recommends_right_away"):
        # A follow-up question next to the recommendations is fine; asking back *instead* of recommending is not.
        first_types = [c["type"] for c in replies[0]["message"]["components"]]
        checks.append(("recommends right away instead of asking back", "model_cards" in first_types, f"shown: {first_types}"))
    if model := exp.get("model_id"):
        got = config and config["model_id"]
        checks.append((f"configures {model}", got == model, f"got {got}"))
    if exp.get("configuration_valid"):
        checks.append(("configuration is valid", bool(config and config["valid"]), "no configuration" if not config else
                       "; ".join(i["message"] for i in config["issues"])))
    if words := exp.get("reply_mentions_any"):
        text = last["message"]["text"].lower().replace("\u2019", "'")  # typographic apostrophes
        checks.append(("reply says it isn't possible", any(w in text for w in words), last["message"]["text"][:120]))

    # Grounding: every euro amount the model writes must come from the data, never be made up.
    for i, reply in enumerate(replies):
        # Allowed: catalog data, the data the back end returned with this reply (state, cards), the customer's words.
        allowed = (catalog_numbers | numbers_in(reply["state"]) | numbers_in(reply["message"]["components"])
                   | numbers_in(case["messages"][: i + 1]))
        invented = [a for a in euro_amounts(reply["message"]["text"]) if a not in allowed]
        checks.append((f"reply {i + 1}: no invented prices", not invented, f"unknown amounts: {invented}"))
    return checks


async def main() -> int:
    load_env_file()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (in the environment or .env); the eval needs the real model.")
        return 2

    from catalog_service.main import app as catalog_app  # noqa: E402
    from agent_service.catalog_client import CatalogClient  # noqa: E402
    from agent_service.config import Settings  # noqa: E402
    from agent_service.main import Runtime, create_app  # noqa: E402

    logging.getLogger().setLevel(logging.WARNING)  # the services log every request; keep the report readable
    usage = UsageLog()
    llm_log = logging.getLogger("agent.llm")
    llm_log.setLevel(logging.INFO)
    llm_log.propagate = False
    llm_log.addHandler(usage)

    cfg = Settings(agent_mode="llm", llm_provider="openai", app_password=None)  # type: ignore[arg-type]
    catalog = CatalogClient("http://catalog", transport=httpx.ASGITransport(app=catalog_app))
    catalog_numbers = numbers_in(await catalog.catalog())
    app = create_app(Runtime(catalog=catalog, cfg=cfg))
    cases = json.loads((HERE / "cases.json").read_text())
    only = set(sys.argv[1:])
    print(f"Model {cfg.llm_model}, {len([c for c in cases if not only or c['id'] in only])} cases\n")

    pin, pout = PRICES.get(cfg.llm_model, PRICES["gpt-5.5"])

    def tokens(calls: list[dict]) -> dict:
        tin, tout = sum(c.get("in", 0) for c in calls), sum(c.get("out", 0) for c in calls)
        return {"calls": len(calls), "input": tin, "output": tout, "cost_usd": round(tin / 1e6 * pin + tout / 1e6 * pout, 4)}

    passed = total = 0
    results: list[dict] = []
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as client:
        for case in cases:
            if only and case["id"] not in only:
                continue
            print(f"● {case['id']}: {case['about']}")
            transcript: list[dict] = []
            first_call, t0 = len(usage.calls), time.perf_counter()
            final = None
            try:
                checks = await run_case(client, case, catalog_numbers, transcript)
            except Exception as exc:  # a crash counts as one failed check, the run continues
                checks = [("conversation completed", False, repr(exc))]
            for name, ok, detail in checks:
                print(f"   {'✓' if ok else '✗'} {name}" + ("" if ok else f"  ({detail})"))
            passed += sum(ok for _, ok, _ in checks)
            total += len(checks)
            print()
            results.append({
                "id": case["id"], "about": case["about"], "expect": case["expect"],
                "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                "transcript": transcript, "final": LAST_STATE.pop(case["id"], None),
                "seconds": round(time.perf_counter() - t0, 1), "usage": tokens(usage.calls[first_call:]),
            })

    run = {"started_at": started_at.isoformat(timespec="seconds"), "model": cfg.llm_model,
           "effort": cfg.llm_effort, "seconds": round(time.perf_counter() - started, 1),
           "passed": passed, "total": total, "usage": tokens(usage.calls), "cases": results}
    path = save_run(run)
    u = run["usage"]
    print(f"Score {passed}/{total} checks passed")
    print(f"{u['calls']} LLM calls, {u['input']:,} input + {u['output']:,} output tokens, "
          f"about ${u['cost_usd']:.2f} at list price, {run['seconds']:.0f} s")
    print(f"Saved {path.relative_to(ROOT)} - see it with: make eval-view")
    return 0 if passed == total else 1


RESULTS = HERE / "results"
LAST_STATE: dict[str, dict] = {}  # case id -> summary of the final state, filled by run_case


def save_run(run: dict) -> Path:
    """One JSON file per run, plus an index the viewer reads (newest first)."""
    RESULTS.mkdir(exist_ok=True)
    stamp = run["started_at"].replace(":", "").replace("+0000", "Z").replace("+00:00", "Z")
    path = RESULTS / f"{stamp}_{run['model']}.json"
    path.write_text(json.dumps(run, indent=1, ensure_ascii=False))
    index = []
    for f in sorted(RESULTS.glob("*.json"), reverse=True):
        if f.name == "index.json":
            continue
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        index.append({"file": f.name, "started_at": r["started_at"], "model": r["model"], "passed": r["passed"],
                      "total": r["total"], "cost_usd": r["usage"]["cost_usd"], "seconds": r["seconds"],
                      "cases": len(r["cases"])})
    (RESULTS / "index.json").write_text(json.dumps(index, indent=1))
    return path


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
