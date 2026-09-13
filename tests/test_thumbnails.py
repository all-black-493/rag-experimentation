from unittest.mock import Mock, patch

import pymupdf
import pytest
from bs4 import BeautifulSoup

from app.ingestion.pdf import render_page_thumbnails
from app.thumbnails import extract_preview_image_url, fetch_and_cache_thumbnail

PNG_MAGIC = b"\x89PNG"


@pytest.fixture
def three_page_pdf(tmp_path):
    path = tmp_path / "doc.pdf"
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"Page {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


def test_renders_only_the_requested_pages(three_page_pdf):
    thumbnails = render_page_thumbnails(three_page_pdf, [1, 3])

    assert sorted(thumbnails) == [1, 3]
    assert all(data.startswith(PNG_MAGIC) for data in thumbnails.values())


def test_ignores_pages_outside_the_document(three_page_pdf):
    """A page number past the end shouldn't raise, just produce nothing."""
    assert sorted(render_page_thumbnails(three_page_pdf, [2, 99, 0])) == [2]


def test_extracts_og_image_as_absolute_url():
    soup = BeautifulSoup('<meta property="og:image" content="/preview.png">', "html.parser")

    url = extract_preview_image_url(soup, "https://example.com/article")

    assert url == "https://example.com/preview.png"


def test_falls_back_to_twitter_image():
    soup = BeautifulSoup('<meta name="twitter:image" content="https://x.test/a.jpg">', "html.parser")

    assert extract_preview_image_url(soup, "https://x.test/") == "https://x.test/a.jpg"


def test_returns_none_when_no_preview_image():
    soup = BeautifulSoup("<meta name='description' content='no image here'>", "html.parser")

    assert extract_preview_image_url(soup, "https://example.com") is None


def test_rejects_non_http_scheme():
    """og:image is page-controlled, so a file:// URL must not reach the fetcher."""
    soup = BeautifulSoup('<meta property="og:image" content="file:///etc/passwd">', "html.parser")

    assert extract_preview_image_url(soup, "https://example.com") is None


def test_rejects_non_image_content_type():
    """A URL that serves HTML instead of an image must not be cached as one."""
    fake_response = Mock(
        status_code=200,
        content=b"<html>not an image</html>",
        headers={"content-type": "text/html"},
    )

    with patch("app.thumbnails.httpx.get", return_value=fake_response):
        assert fetch_and_cache_thumbnail("https://example.com/fake.png") is None
