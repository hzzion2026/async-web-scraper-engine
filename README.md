# Async Web Scraper — Data Extraction Toolkit

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![httpx](https://img.shields.io/badge/httpx-0.28-green.svg)](https://www.python-httpx.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-ready, asynchronous web scraper that extracts structured data — text content,
hyperlinks, images, and metadata — from any web page. Built with **httpx** and **BeautifulSoup**,
it supports concurrent scraping, rate limiting, retry logic, and multiple output formats.

---

## Features

- ⚡ **Fully async** — concurrent scraping with `asyncio` and `httpx`
- 🧱 **Structured extraction** — text, links, images, metadata, and headings
- 📄 **Dual output** — JSON (structured data) and/or Markdown (human-readable reports)
- 🐌 **Rate limiting** — configurable requests per second (polite by default)
- 🔁 **Retry with backoff** — exponential back-off on timeouts and server errors
- 🧪 **User-agent rotation** — cycles through modern browser user agents
- 🛡 **Error resilience** — timeouts, size limits, 4xx/5xx handling
- 🐳 **Docker ready** — containerised with multi-stage build
- ✅ **Fully tested** — comprehensive test suite with pytest

---

## Quick Start

### Installation

```bash
# Clone or copy the project, then:
pip install -r requirements.txt
```

### Basic usage

```bash
# Scrape a single URL (outputs JSON by default)
python app.py https://example.com

# Scrape a single URL and output Markdown
python app.py https://example.com --fmt md

# Output both JSON and Markdown
python app.py https://example.com --fmt both

# Scrape multiple URLs
python app.py https://example.com https://httpbin.org/html --fmt md

# Read URLs from a file (one per line)
echo "https://example.com" > urls.txt
echo "https://httpbin.org/html" >> urls.txt
python app.py urls.txt --fmt both
```

### Advanced usage

```bash
# Control concurrency and rate limiting
python app.py urls.txt --concurrency 10 --rate 8

# Custom timeout and retries
python app.py https://example.com --timeout 60 --max-retries 5

# Disable redirect following
python app.py https://example.com --no-redirects

# Debug logging
python app.py https://example.com --debug

# Specify output directory
python app.py https://example.com -o ./my-data --fmt both
```

---

## Output Formats

### JSON

Each page is serialised into a structured JSON file containing:

| Field              | Description                          |
|--------------------|--------------------------------------|
| `url`              | Scraped URL                          |
| `title`            | Page `<title>`                       |
| `status_code`      | HTTP status (always 200 on success)  |
| `text_content`     | Cleaned visible text                 |
| `links`            | List of `{href, text}` dictionaries  |
| `images`           | List of `{src, alt}` dictionaries    |
| `metadata`         | Meta tags keyed by name/property     |
| `headings`         | H1–H6 tags grouped by level          |
| `scrape_duration_ms` | Time taken for the request          |

### Markdown

Generates a polished, human-readable Markdown report with sections for metadata,
page structure (headings), extracted text, link inventory, and image gallery.

---

## Programmatic Usage

```python
import asyncio
from app import AsyncWebScraper

async def main():
    async with AsyncWebScraper(rate_limit=5.0) as scraper:
        page = await scraper.scrape("https://example.com")
        print(f"Title: {page.title}")
        print(f"Links found: {len(page.links)}")
        print(f"Images found: {len(page.images)}")

        # Save to file
        await scraper.scrape_to_files(
            "https://example.com",
            output_dir="./data",
            fmt="both"
        )

        # Scrape multiple pages concurrently
        urls = [
            "https://example.com",
            "https://httpbin.org/html",
        ]
        results = await scraper.scrape_many(urls, concurrency=5)
        for page in results:
            print(page.to_markdown())

asyncio.run(main())
```

---

## Docker

### Build

```bash
docker build -t async-scraper .
```

### Run

```bash
# Basic usage
docker run --rm -v "$(pwd)/output:/app/output" async-scraper https://example.com

# With custom options
docker run --rm \
  -v "$(pwd)/output:/app/output" \
  async-scraper https://example.com --fmt both --rate 3

# Using a file of URLs
docker run --rm \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/urls.txt:/app/urls.txt:ro" \
  async-scraper urls.txt --fmt md
```

---

## Project Structure

```
scraper-demo/
├── app.py                 # Main application — scraper engine + CLI
├── tests/
│   └── test_scraper.py    # Comprehensive test suite (pytest)
├── requirements.txt       # Python dependencies
├── Dockerfile             # Multi-stage Docker build
├── Makefile               # Common development commands
├── pyproject.toml         # Project metadata and tool config
├── .gitignore             # Git ignore rules
└── README.md              # This file
```

---

## Development

### Setup

```bash
# Create a virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dev dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov
```

### Run tests

```bash
make test
# or
pytest tests/ -v
```

### Run linter

```bash
make lint
# or
ruff check app.py tests/
```

### Coverage

```bash
make coverage
# or
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Configuration

| Parameter         | CLI Flag         | Default | Description                     |
|-------------------|------------------|---------|---------------------------------|
| Rate limit        | `--rate`         | 5.0     | Max requests per second         |
| Concurrency       | `--concurrency`  | 5       | Max concurrent requests         |
| Timeout           | `--timeout`      | 30.0    | HTTP request timeout (seconds)  |
| Max retries       | `--max-retries`  | 3       | Retries on failure              |
| Follow redirects  | `--no-redirects` | True    | Auto-follow HTTP redirects      |

---

## License

This project is provided as a demonstration and is available under the MIT License.
