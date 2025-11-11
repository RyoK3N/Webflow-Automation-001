.PHONY: install run test lint clean

# Detect if we're in a conda/virtualenv
ifdef CONDA_DEFAULT_ENV
    PYTHON := python
else
    PYTHON := python3.11
endif

install:
	@echo "Installing dependencies with pip..."
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e .

run:
	@echo "Starting uvicorn server..."
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	@echo "Running tests..."
	$(PYTHON) -m pytest -v

lint:
	@echo "Linting code..."
	$(PYTHON) -m ruff check app/
	$(PYTHON) -m mypy app/

clean:
	@echo "Cleaning pycache..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

health-check:
	@curl -f http://localhost:8000/health || exit 1