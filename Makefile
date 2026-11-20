.PHONY: install lint format typecheck test run check

DATA ?= data/CST_Case_Study_data.csv

install:  ## Install Python and all dependencies
	uv sync

lint:  ## Check style and common bugs
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-fix lint issues and format code
	uv run ruff check --fix .
	uv run ruff format .

typecheck:  ## Strict static type check
	uv run mypy

test:  ## Run the test suite
	uv run pytest

run:  ## Run the report on the sample data (override with DATA=path)
	uv run python -m fund_analytics $(DATA)

check: lint typecheck test  ## Everything a reviewer should see pass
