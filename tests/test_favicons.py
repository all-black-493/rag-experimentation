from unittest.mock import Mock, patch

from app.favicons import fetch_and_cache_favicon, get_cached_favicon, get_or_fetch_favicon


def test_get_cached_favicon_returns_none_when_uncached(tmp_path, monkeypatch):
    monkeypatch.setattr("app.favicons.CACHE_DIR", tmp_path)

    assert get_cached_favicon("example.com") is None


def test_get_cached_favicon_rejects_malformed_domain(tmp_path, monkeypatch):
    monkeypatch.setattr("app.favicons.CACHE_DIR", tmp_path)

    assert get_cached_favicon("../../etc/passwd") is None


def test_fetch_and_cache_favicon_caches_direct_hit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.favicons.CACHE_DIR", tmp_path)

    fake_response = Mock(status_code=200, content=b"icon-bytes", headers={"content-type": "image/x-icon"})

    with patch("app.favicons.httpx.get", return_value=fake_response) as mock_get:
        result = fetch_and_cache_favicon("example.com")

    assert result == (b"icon-bytes", "image/x-icon")
    mock_get.assert_called_once()
    assert "favicon.ico" in mock_get.call_args[0][0]

    # Second call reads from cache, no further network request.
    with patch("app.favicons.httpx.get") as mock_get_again:
        cached = get_cached_favicon("example.com")
    mock_get_again.assert_not_called()
    assert cached == (b"icon-bytes", "image/x-icon")


def test_fetch_and_cache_favicon_falls_back_to_service_on_404(tmp_path, monkeypatch):
    monkeypatch.setattr("app.favicons.CACHE_DIR", tmp_path)

    not_found = Mock(status_code=404, content=b"")
    fallback_hit = Mock(status_code=200, content=b"fallback-bytes", headers={"content-type": "image/png"})

    with patch("app.favicons.httpx.get", side_effect=[not_found, fallback_hit]) as mock_get:
        result = fetch_and_cache_favicon("example.com")

    assert result == (b"fallback-bytes", "image/png")
    assert mock_get.call_count == 2
    assert "google.com/s2/favicons" in mock_get.call_args_list[1][0][0]


def test_fetch_and_cache_favicon_rejects_malformed_domain(tmp_path, monkeypatch):
    monkeypatch.setattr("app.favicons.CACHE_DIR", tmp_path)

    with patch("app.favicons.httpx.get") as mock_get:
        result = fetch_and_cache_favicon("not/a/domain")

    mock_get.assert_not_called()
    assert result is None


def test_get_or_fetch_favicon_prefers_cache_over_network(tmp_path, monkeypatch):
    monkeypatch.setattr("app.favicons.CACHE_DIR", tmp_path)
    fake_response = Mock(status_code=200, content=b"icon-bytes", headers={"content-type": "image/x-icon"})
    with patch("app.favicons.httpx.get", return_value=fake_response):
        fetch_and_cache_favicon("example.com")

    with patch("app.favicons.httpx.get") as mock_get:
        result = get_or_fetch_favicon("example.com")

    mock_get.assert_not_called()
    assert result == (b"icon-bytes", "image/x-icon")
