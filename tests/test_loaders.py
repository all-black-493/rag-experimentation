from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.ingestion.loaders import load_path, load_text, load_web


def test_load_text_sets_source_and_title(tmp_path: Path):
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello world")

    documents = load_text(file_path)

    assert len(documents) == 1
    assert documents[0].page_content == "hello world"
    assert documents[0].metadata == {
        "source": str(file_path),
        "title": "note.txt",
        "source_type": "text",
    }


def test_load_web_strips_scripts_and_extracts_title():
    html = """
    <html>
        <head><title>Example Page</title></head>
        <body>
            <script>console.log('should be removed')</script>
            <p>Real content.</p>
        </body>
    </html>
    """
    fake_response = Mock(text=html)
    fake_response.raise_for_status = Mock()

    with patch("app.ingestion.loaders.httpx.get", return_value=fake_response) as mock_get:
        documents = load_web("https://example.com/page")

    mock_get.assert_called_once()
    assert documents[0].metadata == {
        "source": "https://example.com/page",
        "title": "Example Page",
        "source_type": "web",
        "favicon_url": "/favicons/example.com",
        "thumbnail_url": None,
    }
    assert "Real content." in documents[0].page_content
    assert "console.log" not in documents[0].page_content


def test_load_web_caches_og_image_as_thumbnail():
    html = """
    <html>
        <head>
            <title>Example Page</title>
            <meta property="og:image" content="https://example.com/preview.png">
        </head>
        <body><p>Real content.</p></body>
    </html>
    """
    fake_response = Mock(text=html)
    fake_response.raise_for_status = Mock()

    with (
        patch("app.ingestion.loaders.httpx.get", return_value=fake_response),
        patch(
            "app.ingestion.loaders.fetch_and_cache_thumbnail", return_value="abc123"
        ) as mock_fetch,
    ):
        documents = load_web("https://example.com/page")

    mock_fetch.assert_called_once_with("https://example.com/preview.png")
    assert documents[0].metadata["thumbnail_url"] == "/thumbnails/abc123"


def test_load_path_rejects_unsupported_extension(tmp_path: Path):
    file_path = tmp_path / "data.csv"
    file_path.write_text("a,b,c")

    with pytest.raises(ValueError, match="Unsupported file type"):
        load_path(file_path)
