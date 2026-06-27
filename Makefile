.PHONY: dev build up down smoke api-compile api-test web-build

dev:
	docker compose up --build

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

smoke:
	python3 scripts/smoke_test.py

api-compile:
	PYTHONPYCACHEPREFIX=/tmp/astock_pycache PYTHONPATH=apps/api apps/api/.venv/bin/python -m compileall apps/api/app

api-test:
	cd apps/api && .venv/bin/python -m pytest

web-build:
	cd apps/web && npm run build
