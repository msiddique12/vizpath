.PHONY: help install install-dev lint format typecheck test test-sdk test-server build clean

# Default target
help:
	@echo "vizpath development commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install      Install all dependencies"
	@echo "  make install-dev  Install with dev dependencies"
	@echo ""
	@echo "Quality:"
	@echo "  make lint         Run linters (ruff + eslint)"
	@echo "  make format       Format code (ruff + prettier)"
	@echo "  make typecheck    Run type checkers (mypy + tsc)"
	@echo ""
	@echo "Testing:"
	@echo "  make test         Run all tests"
	@echo "  make test-sdk     Run SDK tests only"
	@echo "  make test-server  Run server tests only"
	@echo ""
	@echo "Build:"
	@echo "  make build        Build all packages"
	@echo "  make clean        Remove build artifacts"

# Installation
install:
	cd sdk && uv sync
	cd server && uv sync
	cd dashboard && npm install

install-dev:
	cd sdk && uv sync --all-extras
	cd server && uv sync --all-extras
	cd dashboard && npm install

# Linting
lint: lint-python lint-typescript

lint-python:
	cd sdk && uv run ruff check vizpath/
	cd server && uv run ruff check app/

lint-typescript:
	cd dashboard && npm run lint

# Formatting
format: format-python format-typescript

format-python:
	cd sdk && uv run ruff format vizpath/ tests/
	cd server && uv run ruff format app/ tests/

format-typescript:
	cd dashboard && npm run format || npx prettier --write "src/**/*.{ts,tsx}"

# Type checking
typecheck: typecheck-python typecheck-typescript

typecheck-python:
	cd sdk && uv run mypy vizpath/
	cd server && uv run mypy app/

typecheck-typescript:
	cd dashboard && npx tsc --noEmit

# Testing
test: test-sdk test-server

test-sdk:
	cd sdk && uv run pytest tests/ -v

test-server:
	cd server && uv run pytest tests/ -v

test-cov:
	cd sdk && uv run pytest tests/ -v --cov=vizpath --cov-report=html
	cd server && uv run pytest tests/ -v --cov=app --cov-report=html

# Building
build: build-sdk build-dashboard

build-sdk:
	cd sdk && uv build

build-dashboard:
	cd dashboard && npm run build

# Docker
docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

# Development servers
dev-server:
	cd server && uv run uvicorn app.main:app --reload --port 8000

dev-dashboard:
	cd dashboard && npm run dev

# Cleaning
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dashboard/dist 2>/dev/null || true
	rm -rf sdk/dist 2>/dev/null || true
