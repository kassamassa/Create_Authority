import threading
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest


def _insert_article(staging_supabase, article):
    staging_supabase.table("articles").insert(article).execute()
    staging_supabase.created_article_ids.append(article["id"])


def _mock_async_client(mocker, target: str, status_code: int = 200, raise_exc: Exception = None):
    """publisherが使うhttpx.AsyncClientをモックする共通ヘルパー。"""
    mock_response = mocker.Mock()
    mock_response.status_code = status_code
    if raise_exc is not None:
        mock_response.raise_for_status.side_effect = raise_exc
    else:
        mock_response.raise_for_status.return_value = None

    mock_client = mocker.AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mocker.patch(target, return_value=mock_client)
    return mock_client


@pytest.fixture
def rss_feed_url():
    unique_url = f"https://example.com/articles/{uuid.uuid4()}"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test Feed</title>
<link>https://example.com</link><description>test</description>
<item>
<title>DX事例：テスト記事</title>
<description>テスト用の本文です。</description>
<link>{unique_url}</link>
</item>
</channel></rss>""".encode("utf-8")

    class _ArticleFeedHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(xml)

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _ArticleFeedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    yield f"http://127.0.0.1:{port}/feed.xml"

    server.shutdown()
    thread.join()


def test_monitor_health(test_client):
    response = test_client.get("/monitor/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_monitor_status_counts(test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)

    response = test_client.get("/monitor/status")
    assert response.status_code == 200
    assert response.json().get("collected", 0) >= 1


def test_feedback_webhook_save(mocker, test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)
    mocker.patch("app.routers.webhook.analyze_intent", return_value="interest")

    payload = {
        "article_id": dummy_article["id"],
        "sender_email": "reader@example.com",
        "content": "とても興味があります。",
    }
    response = test_client.post("/webhook/feedback", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "interest"
    staging_supabase.created_feedback_ids.append(body["id"])

    result = (
        staging_supabase.table("feedback")
        .select("*")
        .eq("id", body["id"])
        .execute()
    )
    assert len(result.data) == 1
    assert result.data[0]["intent"] == "interest"
    assert result.data[0]["article_id"] == dummy_article["id"]


def test_consultation_slack_notification(mocker, test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)
    mocker.patch("app.routers.webhook.analyze_intent", return_value="consultation")
    notify_mock = mocker.patch("app.routers.webhook.notify_slack")

    payload = {
        "article_id": dummy_article["id"],
        "sender_email": "reader@example.com",
        "content": "個別に詳しく相談したいです。",
    }
    response = test_client.post("/webhook/feedback", json=payload)

    assert response.status_code == 200
    staging_supabase.created_feedback_ids.append(response.json()["id"])

    notify_mock.assert_called_once()
    message = notify_mock.call_args[0][0]
    assert "consultation" in message


def test_newsletter_queue_unique(staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)

    week_start = date.today().isoformat()
    queue_row = {"article_id": dummy_article["id"], "week_start": week_start}

    first = staging_supabase.table("newsletter_queue").insert(queue_row).execute()
    assert first.data

    with pytest.raises(Exception):
        staging_supabase.table("newsletter_queue").insert(queue_row).execute()

    result = (
        staging_supabase.table("newsletter_queue")
        .select("id")
        .eq("article_id", dummy_article["id"])
        .eq("week_start", week_start)
        .execute()
    )
    assert len(result.data) == 1
    # newsletter_queueはarticlesへのON DELETE CASCADEのため、
    # created_article_idsのクリーンアップで自動的に削除される


# --- グループ②: FastAPI ↔ Dify ---

def test_collect_and_process_pipeline(mocker, mock_storage, test_client, staging_supabase, rss_feed_url):
    mocker.patch(
        "app.services.dify.call_dify_workflow",
        return_value={
            "summary": "テスト要約",
            "faq": [{"q": "質問1", "a": "回答1"}],
            "category": "属人化解消",
        },
    )

    response = test_client.post("/pipeline/collect", params={"feed_url": rss_feed_url})

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] == 1
    assert len(body["processed"]) == 1

    article_id = body["processed"][0]["id"]
    staging_supabase.created_article_ids.append(article_id)

    result = staging_supabase.table("articles").select("status").eq("id", article_id).execute()
    assert result.data[0]["status"] == "processed"


def test_dify_result_saved(mocker, mock_storage, test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)
    mocker.patch(
        "app.services.dify.call_dify_workflow",
        return_value={
            "summary": "テスト要約",
            "faq": [{"q": "質問1", "a": "回答1"}],
            "category": "属人化解消",
        },
    )

    response = test_client.post(f"/pipeline/process/{dummy_article['id']}")
    assert response.status_code == 200

    result = staging_supabase.table("articles").select("*").eq("id", dummy_article["id"]).execute()
    row = result.data[0]
    assert row["summary"] == "テスト要約"
    assert row["category"] == "属人化解消"
    assert row["metadata"]["faq"] == [{"q": "質問1", "a": "回答1"}]


def test_status_transition(mocker, mock_storage, test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)
    observed = {}

    def fake_call(url, article_id, category):
        result = staging_supabase.table("articles").select("status").eq("id", article_id).execute()
        observed["during_dify_call"] = result.data[0]["status"]
        return {"summary": "テスト要約", "faq": [{"q": "質問1", "a": "回答1"}], "category": "属人化解消"}

    mocker.patch("app.services.dify.call_dify_workflow", side_effect=fake_call)

    response = test_client.post(f"/pipeline/process/{dummy_article['id']}")
    assert response.status_code == 200

    assert observed["during_dify_call"] == "processing"

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "processed"


def test_dify_timeout_recovery(mocker, mock_storage, test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)
    mocker.patch("app.services.dify.httpx.post", side_effect=httpx.TimeoutException("timeout"))
    notify_mock = mocker.patch("app.services.dify.notify_slack")

    response = test_client.post(f"/pipeline/process/{dummy_article['id']}")
    assert response.status_code == 500

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "rejected"

    mock_storage.remove.assert_called_once()  # tempファイルが削除される
    notify_mock.assert_called_once()


# --- グループ③: FastAPI ↔ 外部配信 ---

def test_sns_publish_integration(mocker, test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)
    mocker.patch("app.services.publisher.generate_carousel_image", return_value=b"fake-png")
    mock_client = _mock_async_client(mocker, "app.services.publisher.httpx.AsyncClient")

    response = test_client.post(f"/pipeline/publish/{dummy_article['id']}")
    assert response.status_code == 200

    assert mock_client.post.call_count == 2  # sns + site

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "published"


def test_site_publish_integration(mocker, test_client, staging_supabase, dummy_article):
    dummy_article["metadata"] = {"faq": [{"q": "質問1", "a": "回答1"}]}
    _insert_article(staging_supabase, dummy_article)
    mocker.patch("app.services.publisher.generate_carousel_image", return_value=b"fake-png")
    mock_client = _mock_async_client(mocker, "app.services.publisher.httpx.AsyncClient")

    response = test_client.post(f"/pipeline/publish/{dummy_article['id']}")
    assert response.status_code == 200

    site_call = next(
        call for call in mock_client.post.call_args_list
        if "content" in call.kwargs.get("json", {})
    )
    assert "jsonld" in site_call.kwargs["json"]
    assert site_call.kwargs["json"]["jsonld"]["mainEntity"][0]["name"] == "質問1"

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "published"


def test_parallel_publish(mocker, test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)
    mocker.patch("app.services.publisher.generate_carousel_image", return_value=b"fake-png")

    mocker.patch(
        "app.services.publisher.publish_to_sns",
        new=mocker.AsyncMock(return_value={"ok": True}),
    )
    mocker.patch(
        "app.services.publisher.publish_to_site",
        new=mocker.AsyncMock(side_effect=Exception("site failed")),
    )

    response = test_client.post(f"/pipeline/publish/{dummy_article['id']}")
    assert response.status_code == 200

    body = response.json()
    assert body["sns"] == {"ok": True}
    assert "error" in body["site"]


def test_newsletter_send_integration(mocker, test_client, staging_supabase, dummy_article):
    dummy_article["status"] = "published"
    _insert_article(staging_supabase, dummy_article)
    week_start = date.today().isoformat()
    staging_supabase.table("newsletter_queue").insert(
        {"article_id": dummy_article["id"], "week_start": week_start}
    ).execute()

    mocker.patch("app.services.newsletter.send_newsletter_email", return_value={"id": "email-1"})

    response = test_client.post("/newsletter/send", json=["reader@example.com"])
    assert response.status_code == 200
    assert response.json()["sent"] is True

    result = (
        staging_supabase.table("newsletter_queue")
        .select("is_sent")
        .eq("article_id", dummy_article["id"])
        .eq("week_start", week_start)
        .execute()
    )
    assert result.data[0]["is_sent"] is True


def test_github_archive_integration(mocker, test_client, staging_supabase, dummy_article):
    dummy_article["metadata"] = {"faq": [{"q": "質問1", "a": "回答1"}]}
    dummy_article["status"] = "published"
    _insert_article(staging_supabase, dummy_article)

    mock_response = mocker.Mock()
    mock_response.raise_for_status.return_value = None
    put_mock = mocker.patch("app.services.archiver.httpx.put", return_value=mock_response)

    response = test_client.post(f"/pipeline/archive/{dummy_article['id']}")
    assert response.status_code == 200

    put_mock.assert_called_once()  # GitHub保存が先に呼ばれる

    result = (
        staging_supabase.table("articles")
        .select("status, archived_at, content")
        .eq("id", dummy_article["id"])
        .execute()
    )
    row = result.data[0]
    assert row["status"] == "archived"
    assert row["archived_at"] is not None
    assert row["content"] is None  # GitHub保存後にNULL化される


def test_github_failure_prevents_null(mocker, test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)

    mock_request = mocker.Mock()
    mock_response = mocker.Mock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=mock_request, response=mock_response
    )
    mocker.patch("app.services.archiver.httpx.put", return_value=mock_response)
    notify_mock = mocker.patch("app.services.archiver.notify_slack")

    response = test_client.post(f"/pipeline/archive/{dummy_article['id']}")
    assert response.status_code == 502

    result = staging_supabase.table("articles").select("content, status").eq("id", dummy_article["id"]).execute()
    row = result.data[0]
    assert row["content"] == dummy_article["content"]  # NULL化されない
    assert row["status"] == "collected"  # statusも変更されない

    notify_mock.assert_called_once()


def test_retry_execution(mocker, test_client, staging_supabase, dummy_article):
    dummy_article["failed_channel"] = "site"
    dummy_article["retry_count"] = 1
    _insert_article(staging_supabase, dummy_article)

    _mock_async_client(mocker, "app.services.publisher.httpx.AsyncClient")

    response = test_client.post(f"/articles/{dummy_article['id']}/retry")
    assert response.status_code == 200

    result = (
        staging_supabase.table("articles")
        .select("retry_count, status, failed_channel")
        .eq("id", dummy_article["id"])
        .execute()
    )
    row = result.data[0]
    assert row["retry_count"] == 2  # 増える
    assert row["status"] == "published"
    assert row["failed_channel"] is None  # 成功したのでクリアされる
