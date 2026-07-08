import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.services.newsletter import current_week_start


def _insert_article(staging_supabase, article):
    staging_supabase.table("articles").insert(article).execute()
    staging_supabase.created_article_ids.append(article["id"])


@pytest.fixture
def rss_feed_url():
    unique_url = f"https://example.com/articles/{uuid.uuid4()}"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>DX事例フィード</title>
<link>https://example.com</link><description>E2Eテスト用フィード</description>
<item>
<title>E2E検証：製造業DX事例</title>
<description>E2Eテスト用の本文です。AI活用によって属人化を解消した事例を紹介します。</description>
<link>{unique_url}</link>
</item>
</channel></rss>""".encode("utf-8")

    class _FeedHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(xml)

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _FeedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    yield f"http://127.0.0.1:{port}/feed.xml"

    server.shutdown()
    thread.join()


def _mock_publisher_http(mocker):
    """publisher.pyのhttpx.AsyncClientをモックしてPostiz/Vercel呼び出しを差し替える。"""
    mock_response = mocker.Mock()
    mock_response.raise_for_status.return_value = None
    mock_client = mocker.AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mocker.patch("app.services.publisher.httpx.AsyncClient", return_value=mock_client)
    return mock_client


# ============================================================
# シナリオ①: 通常フロー
# 収集 → Dify処理 → SNS/サイト公開 → newsletter_queue自動追加
# ============================================================

def test_full_pipeline_flow(mocker, test_client, staging_supabase, rss_feed_url):
    """収集からSNS/サイト公開・newsletter_queue追加まで一連のステータス遷移を検証する。"""
    # Dify(ステップ③)モック
    mocker.patch(
        "app.services.dify.call_dify_workflow",
        return_value={
            "summary": "E2E検証用要約：AIで属人化を解消した製造業事例",
            "faq": [{"q": "DX導入の効果は?", "a": "作業時間を50%削減しました。"}],
            "category": "属人化解消",
        },
    )

    # カルーセル画像生成(ステップ⑤)モック
    mocker.patch("app.services.publisher.generate_carousel_image", return_value=b"fake-carousel-png")

    # Postiz(SNS/ステップ⑥) + Vercel(サイト/ステップ⑦)のHTTPモック
    mock_http = _mock_publisher_http(mocker)

    # ステップ1: POST /pipeline/collect
    response = test_client.post("/pipeline/collect", params={"feed_url": rss_feed_url})
    assert response.status_code == 200
    body = response.json()
    assert body["saved"] == 1, f"保存数が1件のはず: {body}"
    assert len(body["processed"]) == 1, f"処理数が1件のはず: {body}"

    article_id = body["processed"][0]["id"]
    staging_supabase.created_article_ids.append(article_id)

    # ステップ2-5: collected→processing→processedの内部遷移後、最終状態を確認
    result = staging_supabase.table("articles").select("*").eq("id", article_id).execute()
    article_row = result.data[0]
    assert article_row["status"] == "processed"
    assert article_row["summary"] == "E2E検証用要約：AIで属人化を解消した製造業事例"
    assert article_row["category"] == "属人化解消"
    assert article_row["metadata"]["faq"] == [{"q": "DX導入の効果は?", "a": "作業時間を50%削減しました。"}]

    # ステップ6: POST /pipeline/publish/{id}
    response = test_client.post(f"/pipeline/publish/{article_id}")
    assert response.status_code == 200

    # ステップ7-8: SNS(Postiz)とサイト(Vercel)の2回POSTを確認
    assert mock_http.post.call_count == 2  # sns + site

    # ステップ9,11: status=publishedを確認
    result = staging_supabase.table("articles").select("status, published_at").eq("id", article_id).execute()
    row = result.data[0]
    assert row["status"] == "published"
    assert row["published_at"] is not None

    # ステップ10: newsletter_queueへの自動追加を確認
    result = staging_supabase.table("newsletter_queue").select("*").eq("article_id", article_id).execute()
    assert len(result.data) == 1, "newsletter_queueに記事が自動追加されているはず"
    assert result.data[0]["is_sent"] is False


# ============================================================
# シナリオ②: 週次アーカイブフロー
# メルマガ配信 → GitHub保存 → 本文NULL化（失敗時のガード確認含む）
# ============================================================

def test_weekly_archive_flow(mocker, test_client, staging_supabase, dummy_article):
    """メルマガ配信→GitHub保存→本文NULL化の直列実行と、GitHub失敗時のガードを検証する。"""
    # ステップ1: published状態の記事を作成
    dummy_article["status"] = "published"
    _insert_article(staging_supabase, dummy_article)

    # ステップ2: newsletter_queueにキュー追加
    week_start = current_week_start().isoformat()
    staging_supabase.table("newsletter_queue").insert({
        "article_id": dummy_article["id"],
        "week_start": week_start,
    }).execute()

    # ステップ3-4: POST /newsletter/send (Resendモック)
    mocker.patch("app.services.newsletter.send_newsletter_email", return_value={"id": "resend-mock-001"})

    response = test_client.post("/newsletter/send", json=["reader@example.com"])
    assert response.status_code == 200
    assert response.json()["sent"] is True

    # ステップ5: is_sent=trueを確認
    queue_result = (
        staging_supabase.table("newsletter_queue")
        .select("is_sent, sent_at")
        .eq("article_id", dummy_article["id"])
        .eq("week_start", week_start)
        .execute()
    )
    assert queue_result.data[0]["is_sent"] is True
    assert queue_result.data[0]["sent_at"] is not None

    # ステップ6-9: POST /pipeline/archive/{id} (GitHub成功モック)
    mock_gh_response = mocker.Mock()
    mock_gh_response.raise_for_status.return_value = None
    mock_gh_response.json.return_value = {"content": {"html_url": "https://github.com/kassamassa/Create_Authority/archive/test.md"}}
    mocker.patch("app.services.archiver.httpx.put", return_value=mock_gh_response)

    response = test_client.post(f"/pipeline/archive/{dummy_article['id']}")
    assert response.status_code == 200

    # ステップ7-9: GitHub保存が先→contentがNULL化→status=archivedを確認
    result = (
        staging_supabase.table("articles")
        .select("status, archived_at, content")
        .eq("id", dummy_article["id"])
        .execute()
    )
    row = result.data[0]
    assert row["status"] == "archived"
    assert row["archived_at"] is not None
    assert row["content"] is None  # GitHub保存成功後にNULL化される

    # 合格基準: GitHub保存失敗時はNULL化されない(別記事で検証)
    fail_article = {
        **dummy_article,
        "id": str(uuid.uuid4()),
        "source_url": f"https://example.com/articles/{uuid.uuid4()}",
        "status": "published",
        "content": "保持されるべき本文テキストです。",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _insert_article(staging_supabase, fail_article)

    mock_req = mocker.Mock()
    mock_fail_response = mocker.Mock()
    mock_fail_response.status_code = 500
    mock_fail_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Server Error", request=mock_req, response=mock_fail_response
    )
    mocker.patch("app.services.archiver.httpx.put", return_value=mock_fail_response)
    mocker.patch("app.services.archiver.notify_slack")

    fail_response = test_client.post(f"/pipeline/archive/{fail_article['id']}")
    assert fail_response.status_code == 502

    fail_result = (
        staging_supabase.table("articles")
        .select("content, status")
        .eq("id", fail_article["id"])
        .execute()
    )
    fail_row = fail_result.data[0]
    assert fail_row["content"] == "保持されるべき本文テキストです。"  # NULL化されない
    assert fail_row["status"] == "published"  # statusも変更されない


# ============================================================
# シナリオ③: 見込み顧客獲得フロー
# メルマガ返信 → consultation検知 → Slack即時通知 → 手動対応待ち
# ============================================================

def test_lead_acquisition_flow(mocker, test_client, staging_supabase, dummy_article):
    """メルマガ返信のconsultation意図検知・DB保存・Slack通知の一連フローを検証する。"""
    # ステップ1: published状態の記事を作成
    dummy_article["status"] = "published"
    _insert_article(staging_supabase, dummy_article)

    # ステップ4: Claude API (analyze_intent)をconsultationで返すようモック
    mocker.patch("app.routers.webhook.analyze_intent", return_value="consultation")

    # ステップ5: Slack通知をモック
    notify_mock = mocker.patch("app.routers.webhook.notify_slack")

    # ステップ2: POST /webhook/feedback (consultationの返信をシミュレート)
    payload = {
        "article_id": dummy_article["id"],
        "sender_email": "prospect@company.example.com",
        "content": "詳しくお話を聞かせてください。個別に相談したいです。",
    }
    response = test_client.post("/webhook/feedback", json=payload)
    assert response.status_code == 200

    feedback = response.json()
    staging_supabase.created_feedback_ids.append(feedback["id"])

    # ステップ3: feedbackテーブルにintentが正しく保存されることを確認
    result = (
        staging_supabase.table("feedback")
        .select("*")
        .eq("id", feedback["id"])
        .execute()
    )
    assert len(result.data) == 1
    row = result.data[0]
    assert row["intent"] == "consultation"
    assert row["article_id"] == dummy_article["id"]
    assert row["sender_email"] == "prospect@company.example.com"

    # ステップ5: Slack即時通知が届いたことを確認
    notify_mock.assert_called_once()
    message = notify_mock.call_args[0][0]
    assert "consultation" in message

    # ステップ6: is_responded=falseのまま手動対応待ちであることを確認
    assert row["is_responded"] is False
