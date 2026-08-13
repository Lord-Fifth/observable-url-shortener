PYTHON := .venv/Scripts/python.exe
RUFF := .venv/Scripts/ruff.exe

.PHONY: install test lint build up smoke down

install:
	python -m venv .venv
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest

lint:
	$(RUFF) check .
	$(RUFF) format --check .

build:
	docker compose build

up:
	docker compose up --detach --build --wait --wait-timeout 60

smoke:
	$(PYTHON) scripts/smoke.py

down:
	docker compose down --remove-orphans

