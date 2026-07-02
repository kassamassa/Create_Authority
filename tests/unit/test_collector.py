import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.services import collector

RSS_FEED_URL = "https://hnrss.org/newest"
YOUTUBE_VIDEO_WITH_TRANSCRIPT = "dQw4w9WgXcQ"

EMPTY_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Empty Feed</title>
<link>https://example.com</link><description>test</description></channel></rss>"""


class _EmptyFeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.end_headers()
        self.wfile.write(EMPTY_RSS_XML)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def empty_rss_feed_url():
    server = HTTPServer(("127.0.0.1", 0), _EmptyFeedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    yield f"http://127.0.0.1:{port}/empty.xml"

    server.shutdown()
    thread.join()


# --- 正常系（実APIを使用） ---

def test_rss_collect_success():
    articles = collector.collect_from_rss(RSS_FEED_URL)
    assert len(articles) > 0
    first = articles[0]
    assert first["title"]
    assert first["content"] is not None
    assert first["source_url"].startswith("http")


@pytest.mark.asyncio
async def test_newsapi_collect_success(mocker):
    # NewsAPI無料プランはGitHub Actions等の外部サーバーからアクセスできないため、
    # httpx.AsyncClient(NewsAPI呼び出し)とtranslate_to_japanese(Dify翻訳呼び出し)を
    # 両方モックする。
    mock_response = mocker.Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "status": "ok",
        "articles": [
            {
                "title": "Test Article",
                "description": "Test content about DX",
                "url": "https://example.com/test",
                "publishedAt": "2026-07-01T00:00:00Z",
            }
        ],
    }

    mock_client = mocker.AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mocker.patch("app.services.collector.httpx.AsyncClient", return_value=mock_client)

    mocker.patch(
        "app.services.collector.translate_to_japanese",
        side_effect=lambda text: f"日本語訳:{text}",
    )

    articles = await collector.collect_from_newsapi("DX 事例", api_key="dummy-key")

    assert len(articles) == 1
    article = articles[0]
    assert article["title"] == "日本語訳:Test Article"
    assert article["content"] == "日本語訳:Test content about DX"
    assert article["source_url"] == "https://example.com/test"
    assert article["content"] is not None


def test_youtube_transcript_success():
    text = collector.collect_youtube_transcript(YOUTUBE_VIDEO_WITH_TRANSCRIPT)
    assert text is not None
    assert len(text) > 0


def test_empty_feed(empty_rss_feed_url):
    articles = collector.collect_from_rss(empty_rss_feed_url)
    assert articles == []


def test_duplicate_url_skip(staging_supabase, dummy_article):
    first = collector.save_article(staging_supabase, dummy_article)
    assert first is not None
    staging_supabase.created_article_ids.append(first["id"])

    duplicate = dict(dummy_article)
    duplicate["id"] = str(uuid.uuid4())
    result = collector.save_article(staging_supabase, duplicate)
    assert result is None


# --- 異常系（pytest-mockでモック） ---

def test_timeout_slack_notification(mocker):
    mocker.patch("httpx.get", side_effect=httpx.TimeoutException("timeout"))
    notify_mock = mocker.patch("app.services.collector.notify_slack")

    with pytest.raises(collector.CollectorTemporaryError):
        collector.collect_from_rss(RSS_FEED_URL)

    notify_mock.assert_called_once()


def test_youtube_no_transcript(mocker):
    mocker.patch(
        "app.services.collector.YouTubeTranscriptApi.fetch",
        side_effect=collector.TranscriptsDisabled("dummy_video_id"),
    )
    result = collector.collect_youtube_transcript("dummy_video_id")
    assert result is None
