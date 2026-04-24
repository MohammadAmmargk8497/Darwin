.PHONY: install dev-install run ui cli test lint typecheck clean eval

PYTHON ?= python

install:
	poetry install --only main

dev-install:
	poetry install

ui:
	streamlit run ui_app.py

cli:
	$(PYTHON) -m src.agent.main

run: ui

test:
	pytest -q

test-cov:
	pytest --cov=src --cov-report=term-missing

lint:
	ruff check src tests

fmt:
	ruff check --fix src tests
	ruff format src tests

typecheck:
	mypy src

eval:
	$(PYTHON) evaluate_system.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
