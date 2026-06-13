"""
Tests for the async web scraper (app.py).

Uses pytest with pytest-asyncio and httpx's test transport to avoid
real network calls in unit tests.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from app import AsyncWebScraper, ScrapedPage, RateLimiter, build_parser, resolve_urls

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_html() -> str:
    """Return a realistic HTML page for testing."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="description" content="Test page for scraper">
    <meta property="og:title" content="Test OG Title">
    <title>Test Page Title</title>
</head>
<body>
    <header>
        <nav>
            <a href="/">Home</a>
            <a href="/about">About Us</a>
            <a href="/contact">Contact</a>
        </nav>
    </header>
    <main>
        <h1>Welcome to the Test Page</h1>
        <h2>Section One</h2>
        <p>This is a paragraph of text. It contains <strong>important</strong> content.</p>
        <p>Another paragraph with a <a href="https://example.com/details">detailed link</a>.</p>
        <h2>Section Two</h2>
        <p>More text here.</p>
        <img src="/images/logo.png" alt="Logo">
        <img src="https://cdn.example.com/photo.jpg" alt="Photo">
        <img src="/images/decorative.png" alt="">
    </main>
    <footer>
        <p>&copy; 2026 Test Corp</p>
        <a href="https://twitter.com/test">Twitter</a>
        <a href="https://github.com/test">GitHub</a>
        <a href="#section">Same page link (should be deduplicated after fragment strip)</a>
    </footer>
    <script>console.log('ignore this');</script>
    <style>body { color: black; }</style>
</body>
</html>"""


@pytest.fixture
def scraper() -> AsyncWebScraper:
    """Return a scraper instance with fast settings for testing."""
    return AsyncWebScraper(rate_limit=100.0, timeout=5.0, max_retries=1)


@pytest.fixture
def mock_transport(sample_html: str):
    """Return a mock httpx transport that returns the sample HTML."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sample_html)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_no_delay_when_not_needed(self) -> None:
        """RateLimiter should not sleep if the minimum interval has passed."""
        limiter = RateLimiter(requests_per_second=1000.0)
        # Should complete quickly
        import asyncio

        asyncio.run(limiter.acquire())

    def test_infinite_rate(self) -> None:
        """A rate of 0 or negative should disable waiting."""
        limiter = RateLimiter(requests_per_second=0)
        # Should complete immediately
        import asyncio

        asyncio.run(limiter.acquire())

    def test_rate_zero(self) -> None:
        """Exactly zero should not block."""
        limiter = RateLimiter(requests_per_second=0.0)
        import asyncio

        asyncio.run(limiter.acquire())


# ---------------------------------------------------------------------------
# resolve_urls
# ---------------------------------------------------------------------------


class TestResolveUrls:
    def test_single_url(self, tmp_path: Path) -> None:
        """A plain URL should be returned as-is."""
        urls = resolve_urls(["https://example.com"])
        assert urls == ["https://example.com"]

    def test_file_of_urls(self, tmp_path: Path) -> None:
        """If the only argument is a file, read URLs from it."""
        f = tmp_path / "urls.txt"
        f.write_text(
            "https://example.com\n"
            "https://httpbin.org/html\n"
            "# This is a comment\n"
            "  \n"
            "https://python.org\n"
        )
        urls = resolve_urls([str(f)])
        assert urls == [
            "https://example.com",
            "https://httpbin.org/html",
            "https://python.org",
        ]

    def test_multiple_args(self) -> None:
        """Multiple arguments, regardless of files, stay as-is."""
        urls = resolve_urls(["https://a.com", "https://b.com"])
        assert urls == ["https://a.com", "https://b.com"]

    def test_empty_file(self, tmp_path: Path) -> None:
        """An empty file should return an empty list."""
        f = tmp_path / "empty.txt"
        f.write_text("")
        urls = resolve_urls([str(f)])
        assert urls == []


# ---------------------------------------------------------------------------
# ScrapedPage
# ---------------------------------------------------------------------------


class TestScrapedPage:
    def test_to_dict(self) -> None:
        page = ScrapedPage(
            url="https://example.com",
            title="Test",
            status_code=200,
            text_content="Hello world",
            links=[{"href": "https://example.com/page", "text": "page"}],
            images=[{"src": "https://example.com/img.png", "alt": "img"}],
            metadata={"description": ["Test page"]},
            headings={"h1": ["Hello"]},
            scrape_duration_ms=12.3,
        )
        d = page.to_dict()
        assert d["url"] == "https://example.com"
        assert d["title"] == "Test"
        assert d["links"][0]["href"] == "https://example.com/page"
        assert d["scrape_duration_ms"] == 12.3

    def test_to_markdown_includes_title(self) -> None:
        page = ScrapedPage(
            url="https://example.com",
            title="My Page",
            status_code=200,
            text_content="Some text.",
        )
        md = page.to_markdown()
        assert "# My Page" in md
        assert "Some text" in md
        assert "https://example.com" in md

    def test_to_markdown_no_title(self) -> None:
        page = ScrapedPage(
            url="https://example.com",
            title="",
            status_code=200,
            text_content="Text.",
        )
        md = page.to_markdown()
        assert "# Untitled" in md


# ---------------------------------------------------------------------------
# AsyncWebScraper — unit tests (mocked transport)
# ---------------------------------------------------------------------------


class TestAsyncWebScraper:
    @pytest.mark.asyncio
    async def test_scrape_returns_page(self, scraper, mock_transport) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            page = await scraper.scrape("https://example.com")
            assert isinstance(page, ScrapedPage)
            assert page.title == "Test Page Title"
            assert page.status_code == 200

    @pytest.mark.asyncio
    async def test_scrape_extracts_title(self, scraper, mock_transport) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            page = await scraper.scrape("https://example.com")
            assert page.title == "Test Page Title"

    @pytest.mark.asyncio
    async def test_scrape_extracts_text(self, scraper, mock_transport) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            page = await scraper.scrape("https://example.com")
            assert "This is a paragraph of text" in page.text_content
            assert "important" in page.text_content
            # Script and style content should be stripped
            assert "console.log" not in page.text_content
            assert "color: black" not in page.text_content

    @pytest.mark.asyncio
    async def test_scrape_extracts_links(self, scraper, mock_transport) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            page = await scraper.scrape("https://example.com")
            hrefs = [l["href"] for l in page.links]

            # Relative links should be resolved
            assert "https://example.com/" in hrefs
            assert "https://example.com/about" in hrefs
            assert "https://example.com/details" in hrefs
            assert "https://twitter.com/test" in hrefs
            assert "https://github.com/test" in hrefs
            # #section after fragment strip -> https://example.com#section -> https://example.com
            assert "https://example.com" in hrefs  # from #section fragment strip
            assert len(hrefs) == 7

    @pytest.mark.asyncio
    async def test_scrape_extracts_images(self, scraper, mock_transport) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            page = await scraper.scrape("https://example.com")
            srcs = [i["src"] for i in page.images]
            assert "https://example.com/images/logo.png" in srcs
            assert "https://cdn.example.com/photo.jpg" in srcs
            # Image with empty alt should still be included
            assert any("decorative.png" in s for s in srcs)

    @pytest.mark.asyncio
    async def test_scrape_extracts_metadata(self, scraper, mock_transport) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            page = await scraper.scrape("https://example.com")
            assert "description" in page.metadata
            assert "Test page for scraper" in page.metadata["description"]
            assert "og:title" in page.metadata
            assert "Test OG Title" in page.metadata["og:title"]

    @pytest.mark.asyncio
    async def test_scrape_extracts_headings(self, scraper, mock_transport) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            page = await scraper.scrape("https://example.com")
            assert "h1" in page.headings
            assert "Welcome to the Test Page" in page.headings["h1"]
            assert "h2" in page.headings
            assert "Section One" in page.headings["h2"]
            assert "Section Two" in page.headings["h2"]

    @pytest.mark.asyncio
    async def test_scrape_invalid_url(self, scraper) -> None:
        with pytest.raises(ValueError, match="Invalid URL"):
            await scraper.scrape("not-a-url")

    @pytest.mark.asyncio
    async def test_scrape_to_files_json(self, scraper, mock_transport, tmp_path) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            out = await scraper.scrape_to_files(
                "https://example.com", output_dir=str(tmp_path), fmt="json"
            )
            assert out.exists()
            assert out.suffix == ".json"
            data = json.loads(out.read_text())
            assert data["title"] == "Test Page Title"

    @pytest.mark.asyncio
    async def test_scrape_to_files_markdown(self, scraper, mock_transport, tmp_path) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            out = await scraper.scrape_to_files(
                "https://example.com", output_dir=str(tmp_path), fmt="md"
            )
            assert out.exists()
            assert out.suffix == ".md"
            text = out.read_text()
            assert "# Test Page Title" in text

    @pytest.mark.asyncio
    async def test_scrape_to_files_both(self, scraper, mock_transport, tmp_path) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            out = await scraper.scrape_to_files(
                "https://example.com", output_dir=str(tmp_path), fmt="both"
            )
            # Returns the first (JSON) path
            json_path = tmp_path / "example_com.json"
            md_path = tmp_path / "example_com.md"
            assert json_path.exists()
            assert md_path.exists()
            assert out == json_path

    @pytest.mark.asyncio
    async def test_scrape_many(self, scraper, mock_transport) -> None:
        async with httpx.AsyncClient(transport=mock_transport) as client:
            scraper._client = client
            urls = ["https://example.com", "https://example.com/about"]
            results = await scraper.scrape_many(urls, concurrency=2)
            assert len(results) == 2
            for page in results:
                assert isinstance(page, ScrapedPage)

    @pytest.mark.asyncio
    async def test_http_error_status(self) -> None:
        """A 4xx error should raise immediately (no retry)."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        scraper = AsyncWebScraper(rate_limit=100.0, max_retries=3)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper._client = client
            with pytest.raises(httpx.HTTPStatusError):
                await scraper.scrape("https://example.com/not-found")

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_transport) -> None:
        async with AsyncWebScraper(rate_limit=100.0) as scraper:
            async with httpx.AsyncClient(transport=mock_transport) as client:
                scraper._client = client
                page = await scraper.scrape("https://example.com")
                assert page.title == "Test Page Title"
        # Client should be closed after exit
        assert scraper._client is None or scraper._client.is_closed

    def test_url_to_filename(self) -> None:
        assert (
            AsyncWebScraper._url_to_filename("https://example.com/page")
            == "example_com_page"
        )
        assert (
            AsyncWebScraper._url_to_filename("https://sub.example.com/path/to/page")
            == "sub_example_com_path_to_page"
        )


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


class TestCLIParser:
    def test_minimal(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["https://example.com"])
        assert args.urls == ["https://example.com"]
        assert args.fmt == "json"
        assert args.output_dir == "output"

    def test_format_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["https://example.com", "--fmt", "md"])
        assert args.fmt == "md"

    def test_rate_and_concurrency(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["https://example.com", "--rate", "3", "--concurrency", "2"]
        )
        assert args.rate == 3.0
        assert args.concurrency == 2

    def test_no_redirects(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["https://example.com", "--no-redirects"])
        assert args.follow_redirects is False

    def test_version(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--version"])
