# DevMesh Makefile
# ================
# Common development tasks for the DevMesh multi-agent orchestration framework.

.PHONY: help install dev test test-cov lint format clean run docker-build docker-run

PYTHON := python3
PIP := pip3
PYTEST := pytest
DOCKER_IMAGE := devmesh:latest

# Default target
help:
	@echo "DevMesh Development Commands"
	@echo "============================"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Install production dependencies"
	@echo "  make dev            Install development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run all tests"
	@echo "  make test-cov       Run tests with coverage report"
	@echo "  make test-security  Run only security module tests"
	@echo "  make test-rate      Run only rate limiting tests"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint           Run linters (ruff, mypy)"
	@echo "  make format         Format code with black"
	@echo "  make format-check   Check code formatting"
	@echo ""
	@echo "Running:"
	@echo "  make run            Start the DevMesh server"
	@echo "  make run-debug      Start with debug logging"
	@echo "  make run-mock       Start with mock agents"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build   Build Docker image"
	@echo "  make docker-run     Run Docker container"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean          Remove cache files and .pyc"
	@echo "  make reset-db       Reset SQLite database"
	@echo "  make check-tools    Verify available AI CLI tools"

# Installation
install:
	$(PIP) install -r requirements.txt

dev: install
	$(PIP) install pytest pytest-cov pytest-asyncio black ruff mypy bandit

# Testing
test:
	$(PYTEST) tests/ -v

test-cov:
	$(PYTEST) tests/ -v --cov=. --cov-report=term-missing --cov-report=html

test-security:
	$(PYTEST) tests/test_security.py -v

test-rate:
	$(PYTEST) tests/test_rate_limit.py -v

test-core:
	$(PYTEST) tests/test_core.py -v

# Code Quality
lint:
	@echo "Running ruff..."
	ruff check .
	@echo "Running mypy..."
	mypy server.py agent_bridge.py security.py rate_limit.py middleware.py --ignore-missing-imports
	@echo "Running bandit..."
	bandit -r . -f json -o bandit-report.json || true

format:
	black . --line-length 100

format-check:
	black . --line-length 100 --check

# Running
dev-run:
	$(PYTHON) server.py

run:
	DEVMESH_LOG_LEVEL=INFO $(PYTHON) server.py

run-debug:
	DEVMESH_LOG_LEVEL=DEBUG $(PYTHON) server.py

run-mock:
	@echo "Starting server..."
	@$(PYTHON) server.py &
	@sleep 2
	@echo "Starting mock agents..."
	@$(PYTHON) client_mock.py --model architect &
	@$(PYTHON) client_mock.py --model agent1 &
	@$(PYTHON) client_mock.py --model agent2 &
	@echo "DevMesh running with mock agents"
	@echo "Dashboard: http://127.0.0.1:7701"

# Docker
docker-build:
	docker build -t $(DOCKER_IMAGE) .

docker-run:
	docker run -p 7700:7700 -p 7701:7701 -p 7702:7702 $(DOCKER_IMAGE)

docker-dev:
	docker run -it --rm -v $(PWD):/app -p 7700:7700 -p 7701:7701 -p 7702:7702 $(DOCKER_IMAGE) /bin/bash

# Maintenance
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
	rm -f .coverage bandit-report.json

reset-db:
	@echo "Resetting DevMesh database..."
	@rm -f .devmesh/devmesh.db
	@rm -f .devmesh/audit.jsonl
	@rm -f .devmesh/*.bak
	@echo "Database reset complete"

check-tools:
	$(PYTHON) check_tools.py

# CI/CD targets (for GitHub Actions, etc.)
ci-test: test-cov

ci-lint: lint format-check

ci-security:
	bandit -r . -ll
	$(PYTHON) -m safety check || true

# Development helpers
serve-docs:
	@echo "Documentation server not configured yet"

watch:
	@echo "Installing watchdog..."
	$(PIP) install watchdog
	@echo "Watching for changes..."
	watchmedo auto-restart --pattern="*.py" --recursive -- $(PYTHON) server.py
