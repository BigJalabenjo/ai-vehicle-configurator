.PHONY: up down test eval eval-view dev-install diagram

up:            ## build and run the full stack on http://localhost:8080
	docker compose up --build

down:
	docker compose down

dev-install:   ## local virtualenv for running tests without Docker
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

test:
	cd services/catalog && ../../.venv/bin/python -m pytest -q
	cd services/agent && ../../.venv/bin/python -m pytest -q

eval:          ## quality check against the real model, ~$0.50 (CASES=core|adversarial|<ids>; reads OPENAI_API_KEY from .env)
	cd services/agent && ../../.venv/bin/python -m evals.run $(CASES)

eval-view:     ## browse eval runs and start new ones on http://localhost:8090/viewer/
	.venv/bin/python services/agent/evals/serve.py

diagram:       ## regenerate docs/architecture/architecture.{drawio,svg}
	python3 docs/architecture/generate.py
