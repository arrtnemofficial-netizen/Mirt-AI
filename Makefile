.PHONY: format lint test run clean docker-build

# Variables
PYTHON := python
VENV := .venv
BIN := $(VENV)/bin

# Setup
setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip build
	$(BIN)/pip install -e ".[dev]"

# Development
format:
	$(BIN)/ruff format src tests
	$(BIN)/ruff check src tests --fix

lint:
	$(BIN)/ruff check src tests
	$(BIN)/mypy src

test:
	$(BIN)/pytest -v

test-cov:
	$(BIN)/pytest --cov=src --cov-report=html

# Run
run:
	$(BIN)/uvicorn src.server.main:app --reload --host 0.0.0.0 --port 8000

# Docker
docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

# Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
