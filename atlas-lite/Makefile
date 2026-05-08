.PHONY: help install lint format typecheck test cov check all clean

PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip

help:           ## Show this message
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install:        ## Install dev + test deps in editable mode
	$(PIP) install -e ".[dev,test]"

lint:           ## Static lint (ruff)
	$(PYTHON) -m ruff check src tests

format:         ## Auto-format (ruff format)
	$(PYTHON) -m ruff format src tests

typecheck:      ## Type-check (mypy; strict on atlas.api)
	$(PYTHON) -m mypy src/atlas

test:           ## Run unit + API tests
	$(PYTHON) -m pytest

cov:            ## Run tests with coverage gate (≥70% global, see pyproject)
	$(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=xml

cov-api:        ## Strict ≥85% coverage gate for atlas.api package
	$(PYTHON) -m pytest tests/api \
		--cov=src/atlas/api --cov-report=term-missing \
		--cov-fail-under=85

check: lint typecheck cov cov-api  ## Lint + types + coverage gates (CI gate)

all: install check  ## Install + run the full check pipeline

clean:          ## Remove build / cache artifacts
	rm -rf build dist .coverage coverage.xml .pytest_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
