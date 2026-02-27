.PHONY: install test lint format clean

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --tb=short -k "not ui"

lint:
	ruff check paperpilot/

format:
	ruff format paperpilot/

clean:
	find . -type d -name __pycache__ | xargs rm -rf
	find . -name "*.pyc" -delete
	rm -rf dist/ build/ *.egg-info
