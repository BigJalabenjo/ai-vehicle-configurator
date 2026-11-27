# AI Vehicle Configurator

A prototype of a car configurator you can talk to. You describe your needs in plain language; an AI assistant:
- turns them into requirements;
- recommends suitable models and explains why;
- guides you to a valid configuration.

Prices, compatibility and conflicts always come from a rules engine, never from the AI. The configurator view shows the car, its options and price, with the chat alongside.

> The product catalog is fictional: prices, specs and rules are invented for the demo.

## Target architecture (proposal)

![Architecture](docs/architecture/architecture.png)

## How the prototype is built

| Service | Role |
|---|---|
| `services/web` | Browser UI, served by nginx on port 8080 |
| `services/agent` | The assistant: runs the conversation and calls tools (OpenAI or Anthropic) |
| `services/catalog` | Catalog and rules engine: models, options, prices, dependencies, conflicts |

Without an API key, a rule-based guided mode answers instead of the AI, using the same tools and UI.

## Run the prototype locally

**Requires:** Docker with Compose.

```bash
git clone https://github.com/BigJalabenjo/ai-vehicle-configurator.git
cd ai-vehicle-configurator
cp .env.example .env        # add OPENAI_API_KEY=... for AI mode (optional)
docker compose up --build
```

Open **http://localhost:8080**.

Settings in `.env` (all optional):

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` | Turns on AI mode. Without a key, guided mode is used |
| `LLM_MODEL` | Model to use (default `gpt-5.5` or `claude-opus-5-5`) |
| `VOICE_ENABLED` | Hands-free voice mode via the mic button (default on; needs `OPENAI_API_KEY`) |
| `APP_PASSWORD`, `APP_SECRET` | Password-protects the app; leave empty for open access |

`.env` is git-ignored; never commit keys.

## Tests

```bash
make dev-install    # once: creates .venv
make test           # catalog and agent tests, no Docker or API key needed
```

These tests run on GitHub for every push.

## AI eval dashboard

The AI evaluation plays short customer conversations against the real model and checks the results with fixed rules. It checks that needs are understood, the right cards are shown, the configuration stays valid and no prices are made up. Adversarial cases try prompt injection, fake discounts, prompt leaks and rule overrides.

A run uses the `OPENAI_API_KEY` from `.env` and costs about US$0.25–0.50.

```bash
make dev-install    # once, if not done yet
make eval-view      # dashboard at http://localhost:8090/viewer/
```

In the dashboard:
- **Run evaluation** starts a run. Choose all, core or adversarial cases and the model. *Include deliberate failure* adds a case that always fails, to see what a failure looks like.
- Results show per run and per case: the checks with the reason for each failure, the full conversations, and tokens, cost and duration.
- Results are saved locally in `services/agent/evals/results/`, and test cases are in `services/agent/evals/cases.json`.