.PHONY: help install test lint coverage clean run docker-build docker-run

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	pip install -r requirements.txt

test: ## Run tests
	python -m pytest tests/ -v --tb=short --asyncio-mode=auto

coverage: ## Run tests with coverage report
	python -m pytest tests/ --cov=app --cov-report=term-missing --cov-report=html --asyncio-mode=auto

lint: ## Lint the code
	python -m ruff check app.py tests/

format: ## Auto-format code
	python -m ruff format app.py tests/

clean: ## Remove generated files
	rm -rf output/
	rm -rf __pycache__ .pytest_cache .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

run: ## Scrape a URL (usage: make run URL=https://example.com)
	python app.py $(URL)

run-md: ## Scrape a URL to Markdown (usage: make run-md URL=https://example.com)
	python app.py $(URL) --fmt md

run-both: ## Scrape a URL to JSON + Markdown
	python app.py $(URL) --fmt both

docker-build: ## Build Docker image
	docker build -t async-scraper .

docker-run: ## Run Docker container (usage: make docker-run URL=https://example.com)
	docker run --rm -v "$(PWD)/output:/app/output" async-scraper $(URL)
