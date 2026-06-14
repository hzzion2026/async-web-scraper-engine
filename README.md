# Async Web Scraper Engine

A high-performance async web scraping engine built with Python, designed for extracting structured data at scale. Features token-bucket rate limiting, automatic retry with exponential backoff, and multi-format export.

## Project Overview

| Attribute | Detail |
|-----------|--------|
| Type | Data Extraction Engine |
| Pattern | Async Producer-Consumer |
| Output | JSON, Markdown, structured dicts |
| Deployment | Docker (multi-stage) or native Python |

## Technical Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.11 (asyncio) |
| HTTP | httpx (async) |
| Parsing | BeautifulSoup 4 |
| CLI | argparse |
| Container | Docker (multi-stage build) |
| Testing | pytest + httpx.MockTransport |

## Key Features

- Fully async httpx.AsyncClient with configurable concurrency
- Token-bucket rate limiter prevents IP throttling
- Exponential backoff retry with jitter on 5xx/timeout
- User-agent rotation randomized per request
- Structured output: text, links, images, metadata, headings
- Dual export: JSON + Markdown formats
- Programmatic API + CLI interface
- 100% mock-tested with zero network calls

## Quick Start

```bash
pip install -r requirements.txt
python app.py https://example.com --fmt json --output data.json
```
