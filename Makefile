# Makefile for Quant-Ollama-Analyst
# Professional development workflow automation

.PHONY: help install install-dev test lint format type-check clean build docs pre-commit

# Default target
help:
	@echo "Quant-Ollama-Analyst - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install          Install production dependencies"
	@echo "  make install-dev      Install development dependencies"
	@echo "  make pre-commit       Install pre-commit hooks"
	@echo ""
	@echo "Development:"
	@echo "  make test             Run test suite"
	@echo "  make test-cov         Run tests with coverage report"
	@echo "  make lint             Run linters (ruff, bandit)"
	@echo "  make format           Format code (black, isort)"
	@echo "  make type-check       Run type checker (mypy)"
	@echo "  make check            Run all checks (lint + type-check + test)"
	@echo ""
	@echo "Cleaning:"
	@echo "  make clean            Remove build artifacts"
	@echo "  make clean-all        Deep clean including cache"
	@echo ""
	@echo "Build:"
	@echo "  make build            Build distribution packages"
	@echo "  make docs             Build documentation"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

pre-commit:
	pre-commit install
	pre-commit install --hook-type commit-msg

# Testing
test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

test-watch:
	pytest-watch tests/ -v

# Code quality
lint:
	@echo "Running Ruff..."
	ruff check src/ tests/
	@echo "Running Bandit..."
	bandit -r src/ -ll

format:
	@echo "Running Black..."
	black src/ tests/
	@echo "Running isort..."
	isort src/ tests/
	@echo "Running Ruff autofix..."
	ruff check --fix src/ tests/

type-check:
	mypy src/

# Combined checks
check: lint type-check test
	@echo "✅ All checks passed!"

# Cleaning
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf .mypy_cache/
	rm -f coverage.xml
	rm -f .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

clean-all: clean
	rm -rf .venv/
	rm -rf venv/
	rm -rf logs/*.log

# Build
build: clean
	python -m build

# Documentation (future)
docs:
	@echo "Documentation generation coming soon..."

# Development server (future)
run:
	python src/main.py

# Version management
version:
	@grep "^version" pyproject.toml | cut -d'"' -f2

bump-patch:
	@echo "Bumping patch version..."
	# Add version bumping logic here

bump-minor:
	@echo "Bumping minor version..."
	# Add version bumping logic here

bump-major:
	@echo "Bumping major version..."
	# Add version bumping logic here
