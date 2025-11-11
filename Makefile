.PHONY: install run test lint clean docker-build docker-run health-check setup

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
	@echo "Installation complete!"

setup: install
	@echo "Setting up data directory..."
	@mkdir -p app/data
	@if [ ! -f app/data/pages.json ]; then \
		cp app/data/pages.json.example app/data/pages.json 2>/dev/null || \
		echo '[]' > app/data/pages.json; \
	fi
	@if [ ! -f app/data/audit_log.json ]; then \
		echo '[]' > app/data/audit_log.json; \
	fi
	@if [ ! -f .env ]; then \
		cp .env.example .env 2>/dev/null || echo "No .env.example found"; \
	fi
	@echo "Setup complete!"

run:
	@echo "Starting uvicorn server..."
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --log-level info

run-prod:
	@echo "Starting production server..."
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level warning

test:
	@echo "Running tests..."
	$(PYTHON) -m pytest -v --cov=app --cov-report=html --cov-report=term

lint:
	@echo "Linting code..."
	$(PYTHON) -m ruff check app/
	$(PYTHON) -m mypy app/ || true

format:
	@echo "Formatting code..."
	$(PYTHON) -m ruff format app/

clean:
	@echo "Cleaning pycache and build artifacts..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov 2>/dev/null || true
	@echo "Clean complete!"

health-check:
	@echo "Checking application health..."
	@curl -f http://localhost:8000/health || exit 1

docker-build:
	@echo "Building Docker image..."
	docker build -f deployments/Dockerfile -t seo-automation:latest .

docker-run:
	@echo "Starting Docker container..."
	docker-compose -f deployments/docker-compose.yml up -d

docker-stop:
	@echo "Stopping Docker container..."
	docker-compose -f deployments/docker-compose.yml down

docker-logs:
	@echo "Viewing Docker logs..."
	docker-compose -f deployments/docker-compose.yml logs -f

dev:
	@echo "Starting development environment..."
	@make setup
	@make run

help:
	@echo "Available commands:"
	@echo "  make install      - Install Python dependencies"
	@echo "  make setup        - Setup data directories and config files"
	@echo "  make run          - Run development server"
	@echo "  make run-prod     - Run production server (multi-worker)"
	@echo "  make test         - Run tests with coverage"
	@echo "  make lint         - Run code linters"
	@echo "  make format       - Format code"
	@echo "  make clean        - Clean build artifacts"
	@echo "  make health-check - Check application health"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-run   - Run with Docker Compose"
	@echo "  make docker-stop  - Stop Docker containers"
	@echo "  make docker-logs  - View Docker logs"
	@echo "  make dev          - Setup and run development server"