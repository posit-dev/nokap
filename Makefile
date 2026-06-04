.PHONY: help
help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: test
test: ## Run tests
	@pytest tests \
		--cov=nokap \
		--cov-report=term-missing \
		--durations 10

.PHONY: test-integration
test-integration: ## Run integration tests (requires Chrome)
	@pytest tests/test_integration.py -v

.PHONY: test-unit
test-unit: ## Run unit tests only (no Chrome required)
	@pytest tests \
		--ignore=tests/test_integration.py \
		--durations 10

.PHONY: lint
lint: ## Run ruff formatter and linter
	@ruff format
	@ruff check --fix

.PHONY: check-format
check-format: ## Check code formatting without making changes
	@ruff format --check
	@ruff check

.PHONY: type-check
type-check: ## Run type checking with pyright
	@pyright nokap

.PHONY: check
check: lint type-check test ## Run all checks (lint, type-check, test)

.PHONY: clean
clean: clean-build clean-pyc clean-test ## Remove all build, test, coverage and Python artifacts

.PHONY: clean-build
clean-build: ## Remove build artifacts
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +

.PHONY: clean-pyc
clean-pyc: ## Remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

.PHONY: clean-test
clean-test: ## Remove test and coverage artifacts
	rm -f .coverage
	rm -fr htmlcov/
	rm -fr .pytest_cache

.PHONY: build
build: clean ## Build source and wheel distribution
	@python3 -m build
	ls -l dist
