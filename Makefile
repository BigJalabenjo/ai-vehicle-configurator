.PHONY: up down test dev-install diagram

up:            ## build and run the full stack on http://localhost:8080
	docker compose up --build

down:
	docker compose down

dev-install:   ## local virtualenv for running tests without Docker
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

test:
	cd services/catalog && ../../.venv/bin/python -m pytest -q
	cd services/agent && ../../.venv/bin/python -m pytest -q

diagram:       ## regenerate docs/architecture/architecture.{drawio,svg}
	python3 docs/architecture/generate.py
