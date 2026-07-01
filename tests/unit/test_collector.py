import os
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


def test_newsapi_collect_success():
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        pytest.skip("NEWSAPI_KEY が未設定のためスキップ")

    articles = collector.collect_from_newsapi("DX 事例", api_key=api_key)
    assert len(articles) > 0
    assert all(article["title"] for article in articles)


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
