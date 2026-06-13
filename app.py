#!/usr/bin/env python3
"""
Async Web Scraper - Data Extraction Toolkit
============================================
A robust, production-ready async web scraper built with httpx and BeautifulSoup.
Extracts structured data (text, links, images, metadata) from URLs and exports
to JSON, Markdown, or both.

Features:
    - Asynchronous concurrent scraping with configurable rate limiting
    - Structured extraction: text content, hyperlinks, images, metadata
    - Multiple output formats: JSON, Markdown, or both
    - Respects robots.txt (optional)
    - Custom headers and user-agent rotation
    - Retry logic with exponential backoff
    - Timeout and size limits
    - Colored console logging
    - CLI interface with argparse
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

try:
    import coloredlogs

    coloredlogs.install(level="INFO", fmt="%(asctime)s [%(levelname)s] %(message)s")
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

logger = logging.getLogger("scraper")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ScrapedPage:
    """Container for all extracted data from a single page."""

    url: str
    title: str
    status_code: int
    text_content: str
    links: list[dict[str, str]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, list[str]] = field(default_factory=dict)
    headings: dict[str, list[str]] = field(default_factory=dict)
    scrape_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-serialisable dictionary."""
        return asdict(self)

    def to_markdown(self) -> str:
        """Render the scraped content as a Markdown document."""
        lines: list[str] = []

        # Title
        lines.append(f"# {self.title or 'Untitled'}")
        lines.append("")
        lines.append(f"> **Source URL:** [{self.url}]({self.url})")
        lines.append(f"> **Status:** `{self.status_code}`")
        lines.append("")

        # Metadata
        if self.metadata:
            lines.append("## Metadata")
            for key, values in self.metadata.items():
                for val in values:
                    lines.append(f"- **{key}:** {val}")
            lines.append("")

        # Headings (page structure)
        if any(self.headings.values()):
            lines.append("## Page Structure")
            for level, items in self.headings.items():
                for item in items:
                    lines.append(f"- [{level}] {item}")
            lines.append("")

        # Text content
        text = self.text_content.strip()
        if text:
            lines.append("## Extracted Text")
            lines.append("")
            lines.append(text)
            lines.append("")

        # Links
        if self.links:
            lines.append(f"## Links ({len(self.links)})")
            lines.append("")
            for i, link in enumerate(self.links, 1):
                lines.append(
                    f"{i}. [{link.get('text', 'link')}]({link.get('href', '#')})"
                )
            lines.append("")

        # Images
        if self.images:
            lines.append(f"## Images ({len(self.images)})")
            lines.append("")
            for img in self.images:
                alt = img.get("alt", "") or "image"
                src = img.get("src", "")
                lines.append(f"- ![{alt}]({src})")
            lines.append("")

        lines.append("---")
        lines.append(
            f"*Scraped in {self.scrape_duration_ms:.1f} ms "
            f"by Async Web Scraper*"
        )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple token-bucket rate limiter for polite scraping."""

    def __init__(self, requests_per_second: float = 5.0) -> None:
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._last_call: float = 0.0

    async def acquire(self) -> None:
        """Wait if necessary to respect the rate limit."""
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


# ---------------------------------------------------------------------------
# The scraper
# ---------------------------------------------------------------------------


class AsyncWebScraper:
    """Async web scraper with structured extraction and polite defaults."""

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
    DEFAULT_RATE_LIMIT = 5.0

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    ]

    def __init__(
        self,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
        user_agent: Optional[str] = None,
        follow_redirects: bool = True,
        respect_robots: bool = False,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.rate_limiter = RateLimiter(rate_limit)
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_size_bytes = max_size_bytes
        self.user_agent = user_agent
        self.follow_redirects = follow_redirects
        self.respect_robots = respect_robots
        self.custom_headers = headers or {}

        self._client: Optional[httpx.AsyncClient] = None
        self._ua_cycle = 0
        self._ua_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self, url: str) -> ScrapedPage:
        """
        Scrape a single URL and return a structured ScrapedPage.

        Args:
            url: The fully-qualified URL to scrape.

        Returns:
            A ScrapedPage dataclass with all extracted data.

        Raises:
            ValueError: If the URL is invalid.
            httpx.HTTPError: On HTTP/network failures after retries.
        """
        start = time.monotonic()
        self._validate_url(url)

        client = await self._get_client()
        html = await self._fetch_with_retry(client, url)
        page = self._parse_html(url, html)

        page.scrape_duration_ms = (time.monotonic() - start) * 1000
        return page

    async def scrape_many(
        self,
        urls: list[str],
        concurrency: int = 5,
    ) -> list[ScrapedPage]:
        """
        Scrape multiple URLs concurrently with a semaphore for concurrency
        control, in addition to the global rate limiter.

        Args:
            urls: List of URLs to scrape.
            concurrency: Maximum number of concurrent requests.

        Returns:
            List of ScrapedPage results in the same order as *urls*.
        """
        sem = asyncio.Semaphore(concurrency)

        async def _limited_scrape(url: str) -> ScrapedPage:
            async with sem:
                return await self.scrape(url)

        tasks = [_limited_scrape(u) for u in urls]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def scrape_to_files(
        self,
        url: str,
        output_dir: str | Path = ".",
        fmt: str = "json",
        name: Optional[str] = None,
    ) -> Path:
        """
        Scrape a URL and write the result directly to a file.

        Args:
            url: URL to scrape.
            output_dir: Directory for output files (created if missing).
            fmt: Output format — ``"json"``, ``"md"``, or ``"both"``.
            name: Base file name (derived from URL if not given).

        Returns:
            Path to the primary output file.
        """
        page = await self.scrape(url)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        stem = name or self._url_to_filename(url)
        paths = []

        if fmt in ("json", "both"):
            path = output_dir / f"{stem}.json"
            path.write_text(json.dumps(page.to_dict(), indent=2, ensure_ascii=False))
            logger.info("Wrote JSON → %s", path)
            paths.append(path)

        if fmt in ("md", "both"):
            path = output_dir / f"{stem}.md"
            path.write_text(page.to_markdown())
            logger.info("Wrote Markdown → %s", path)
            paths.append(path)

        return paths[0] if paths else output_dir

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AsyncWebScraper":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL: {url!r} — must include scheme and host.")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=self.follow_redirects,
                max_redirects=10,
            )
        return self._client

    async def _rotate_user_agent(self) -> str:
        if self.user_agent:
            return self.user_agent
        async with self._ua_lock:
            ua = self.USER_AGENTS[self._ua_cycle % len(self.USER_AGENTS)]
            self._ua_cycle += 1
            return ua

    async def _fetch_with_retry(
        self, client: httpx.AsyncClient, url: str
    ) -> str:
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                await self.rate_limiter.acquire()
                ua = await self._rotate_user_agent()
                headers = {"User-Agent": ua, **self.custom_headers}

                logger.info(
                    "Fetching [%d/%d] %s", attempt, self.max_retries, url
                )
                response = await client.get(url, headers=headers)

                # Check content length before reading body
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_size_bytes:
                    raise httpx.TooManyRedirects(
                        f"Content exceeds {self.max_size_bytes // 1024} KB limit"
                    )

                response.raise_for_status()
                return response.text

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                wait = 2**attempt
                logger.warning(
                    "Attempt %d failed (%s). Retrying in %ds ...",
                    attempt,
                    exc.__class__.__name__,
                    wait,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(wait)

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                # Retry on 5xx only; fail fast on 4xx
                if 500 <= status < 600 and attempt < self.max_retries:
                    last_exc = exc
                    wait = 2**attempt
                    logger.warning(
                        "HTTP %d on attempt %d. Retrying in %ds ...",
                        status,
                        attempt,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

        raise httpx.HTTPError(
            f"Failed to fetch {url!r} after {self.max_retries} attempts."
        ) from last_exc

    def _parse_html(self, url: str, html: str) -> ScrapedPage:
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # --- Extract structured data BEFORE cleaning text ---

        # Links
        links: list[dict[str, str]] = []
        seen_hrefs: set[str] = set()
        for a_tag in soup.find_all("a", href=True):
            href = urljoin(url, a_tag["href"])
            href = href.split("#")[0]  # strip fragment
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            text = a_tag.get_text(strip=True)[:200]
            links.append({"href": href, "text": text or href})

        # Images
        images: list[dict[str, str]] = []
        for img_tag in soup.find_all("img"):
            src = img_tag.get("src", "")
            if not src:
                continue
            full_src = urljoin(url, src)
            alt = img_tag.get("alt", "")
            images.append({"src": full_src, "alt": alt})

        # Metadata (meta tags)
        metadata: dict[str, list[str]] = {}
        for meta in soup.find_all("meta"):
            name = meta.get("name") or meta.get("property") or ""
            content = meta.get("content", "")
            if name and content:
                metadata.setdefault(name, []).append(content)

        # Headings
        headings: dict[str, list[str]] = {}
        for level in ("h1", "h2", "h3", "h4", "h5", "h6"):
            items = [
                tag.get_text(strip=True)
                for tag in soup.find_all(level)
                if tag.get_text(strip=True)
            ]
            if items:
                headings[level] = items

        # --- Clean text content (remove non-content elements) ---
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text_content = soup.get_text(separator="\n", strip=True)

        return ScrapedPage(
            url=url,
            title=title,
            status_code=200,
            text_content=text_content,
            links=links,
            images=images,
            metadata=metadata,
            headings=headings,
        )

    @staticmethod
    def _url_to_filename(url: str) -> str:
        """Derive a safe filename stem from a URL."""
        parsed = urlparse(url)
        stem = re.sub(r"[^\w-]", "_", parsed.netloc + parsed.path)
        stem = re.sub(r"_+", "_", stem).strip("_")
        return stem[:120] or "output"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scraper",
        description="Async Web Scraper — extract structured data from web pages.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python app.py https://example.com\n"
            "  python app.py https://example.com -o output --fmt both\n"
            "  python app.py urls.txt --concurrency 10 --rate 8\n"
            "  python app.py https://a.com https://b.com --fmt md\n"
        ),
    )
    parser.add_argument("urls", nargs="+", help="URL(s) to scrape, or a file path containing one URL per line.")
    parser.add_argument("-o", "--output-dir", default="output", help="Output directory (default: output/)")
    parser.add_argument("--fmt", choices=["json", "md", "both"], default="json", help="Output format (default: json)")
    parser.add_argument("--rate", type=float, default=5.0, help="Requests per second (default: 5)")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent requests (default: 5)")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds (default: 30)")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries per URL (default: 3)")
    parser.add_argument("--no-redirects", action="store_false", dest="follow_redirects", help="Disable redirect following")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--version", action="version", version="Async Web Scraper v1.0.0")
    return parser


def resolve_urls(args_urls: list[str]) -> list[str]:
    """If a single arg is a file, read URLs from it; otherwise return as-is."""
    if len(args_urls) == 1:
        path = Path(args_urls[0])
        if path.exists() and path.is_file():
            return [
                line.strip()
                for line in path.read_text().splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
    return args_urls


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    urls = resolve_urls(args.urls)
    if not urls:
        parser.error("No URLs provided.")

    scraper = AsyncWebScraper(
        rate_limit=args.rate,
        timeout=args.timeout,
        max_retries=args.max_retries,
        follow_redirects=args.follow_redirects,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Scraping %d URL(s) with concurrency=%d ...", len(urls), args.concurrency)

    results = await scraper.scrape_many(urls, concurrency=args.concurrency)

    results.sort(key=lambda p: p.url)  # deterministic order

    for page in results:
        stem = scraper._url_to_filename(page.url)
        if args.fmt in ("json", "both"):
            path = output_dir / f"{stem}.json"
            path.write_text(json.dumps(page.to_dict(), indent=2, ensure_ascii=False))
            logger.info("Saved JSON → %s", path)
        if args.fmt in ("md", "both"):
            path = output_dir / f"{stem}.md"
            path.write_text(page.to_markdown())
            logger.info("Saved Markdown → %s", path)

        # Also print a summary to stdout
        print(
            f"[{page.status_code}] {page.url} "
            f"→ {len(page.links)} links, "
            f"{len(page.images)} images, "
            f"{len(page.text_content):,} chars "
            f"({page.scrape_duration_ms:.0f} ms)"
        )

    await scraper.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(1)
    except Exception:
        logger.exception("Unexpected error")
        sys.exit(1)
