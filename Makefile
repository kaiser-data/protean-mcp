.PHONY: install dev test lint format build publish run clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check server.py tests/

format:
	ruff format server.py tests/

build:
	python -m build

publish:
	python -m twine upload dist/*

run:
	python server.py

clean:
	rm -rf dist/ build/ *.egg-info __pycache__ .pytest_cache
