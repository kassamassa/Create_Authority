from datetime import date

import pytest


def _insert_article(staging_supabase, article):
    staging_supabase.table("articles").insert(article).execute()
    staging_supabase.created_article_ids.append(article["id"])


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
