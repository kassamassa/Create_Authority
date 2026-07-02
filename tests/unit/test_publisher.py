import asyncio

import httpx
import pytest

from app.services import publisher


def _insert_dummy_article(staging_supabase, dummy_article):
    staging_supabase.table("articles").insert(dummy_article).execute()
    staging_supabase.created_article_ids.append(dummy_article["id"])


# --- notify_slack ---

def test_notify_slack_skips_when_webhook_not_configured(mocker):
    mocker.patch.object(publisher, "SLACK_WEBHOOK_URL", "")
    post_mock = mocker.patch("httpx.post")

    publisher.notify_slack("テストメッセージ")

    post_mock.assert_not_called()


def test_notify_slack_posts_when_webhook_configured(mocker):
    mocker.patch.object(publisher, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/dummy")
    post_mock = mocker.patch("httpx.post")

    publisher.notify_slack("テストメッセージ")

    post_mock.assert_called_once()


# --- 正常系(ステップ⑤⑥⑦) ---
# Postiz/Vercel/HTML→PNGレンダラーは実際の認証情報が存在しないため、
# 外部呼び出し部分をmocker.patchで差し替え、状態遷移・並列実行・エラー判別の
# ロジックを検証する。

def test_carousel_image_generation(mocker):
    mocker.patch(
        "app.services.publisher.render_html_to_png",
        return_value=b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes",
    )
    article = {"title": "テスト記事", "summary": "テスト要約", "category": "属人化解消"}

    image = publisher.generate_carousel_image(article)

    assert isinstance(image, bytes)
    assert image.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_sns_publish_success(mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mock_response = mocker.Mock()
    mock_response.raise_for_status.return_value = None
    mock_client = mocker.AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mocker.patch("app.services.publisher.httpx.AsyncClient", return_value=mock_client)

    await publisher.publish_to_sns(staging_supabase, dummy_article, b"fake-image-bytes")

    mock_client.post.assert_called_once()

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "published"


@pytest.mark.asyncio
async def test_site_publish_success(mocker, staging_supabase, dummy_article):
    dummy_article["metadata"] = {"faq": [{"q": "質問1", "a": "回答1"}]}
    _insert_dummy_article(staging_supabase, dummy_article)

    mock_response = mocker.Mock()
    mock_response.raise_for_status.return_value = None
    mock_client = mocker.AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mocker.patch("app.services.publisher.httpx.AsyncClient", return_value=mock_client)

    await publisher.publish_to_site(staging_supabase, dummy_article)

    sent_payload = mock_client.post.call_args.kwargs["json"]
    assert "jsonld" in sent_payload
    assert sent_payload["jsonld"]["mainEntity"][0]["name"] == "質問1"

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "published"


@pytest.mark.asyncio
async def test_parallel_execution(mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    gather_spy = mocker.spy(asyncio, "gather")

    async def _slow_success(*args, **kwargs):
        await asyncio.sleep(0.2)
        return {"ok": True}

    async def _slow_failure(*args, **kwargs):
        await asyncio.sleep(0.2)
        raise publisher.PublishConfigError("site failed")

    mocker.patch("app.services.publisher.generate_carousel_image", return_value=b"fake-png")
    mocker.patch("app.services.publisher.publish_to_sns", side_effect=_slow_success)
    mocker.patch("app.services.publisher.publish_to_site", side_effect=_slow_failure)

    start = asyncio.get_event_loop().time()
    result = await publisher.publish_article_parallel(staging_supabase, dummy_article)
    elapsed = asyncio.get_event_loop().time() - start

    gather_spy.assert_called_once()
    # 逐次実行なら0.4秒以上かかるが、並列実行なら0.2秒程度で完了するはず
    assert elapsed < 0.35
    # 片方(site)が失敗しても、成功した方(sns)の結果は返る
    assert result["sns"] == {"ok": True}
    assert "error" in result["site"]


# --- 異常系(pytest-mockでモック) ---

@pytest.mark.asyncio
async def test_sns_publish_5xx(mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mock_request = mocker.Mock()
    mock_response = mocker.Mock()
    mock_response.status_code = 502
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "502 Bad Gateway", request=mock_request, response=mock_response
    )
    mock_client = mocker.AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mocker.patch("app.services.publisher.httpx.AsyncClient", return_value=mock_client)
    notify_mock = mocker.patch("app.services.publisher.notify_slack")
    retry_spy = mocker.spy(publisher, "schedule_retry")

    with pytest.raises(publisher.PublishTemporaryError):
        await publisher.publish_to_sns(staging_supabase, dummy_article, b"fake-image-bytes")

    retry_spy.assert_called_once()
    scheduled = retry_spy.spy_return
    assert scheduled["channel"] == "sns"
    assert publisher.RETRY_DELAY_SECONDS == 3600  # 1時間後リトライ

    result = (
        staging_supabase.table("articles")
        .select("failed_channel, retry_count")
        .eq("id", dummy_article["id"])
        .execute()
    )
    assert result.data[0]["failed_channel"] == "sns"
    assert result.data[0]["retry_count"] == 1

    notify_mock.assert_called_once()
    assert "一時障害" in notify_mock.call_args[0][0]


@pytest.mark.asyncio
async def test_site_publish_4xx(mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mock_request = mocker.Mock()
    mock_response = mocker.Mock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized", request=mock_request, response=mock_response
    )
    mock_client = mocker.AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mocker.patch("app.services.publisher.httpx.AsyncClient", return_value=mock_client)
    notify_mock = mocker.patch("app.services.publisher.notify_slack")
    retry_spy = mocker.spy(publisher, "schedule_retry")

    with pytest.raises(publisher.PublishConfigError):
        await publisher.publish_to_site(staging_supabase, dummy_article)

    retry_spy.assert_not_called()  # 4xxはリトライ対象外

    notify_mock.assert_called_once()
    message = notify_mock.call_args[0][0]
    assert "設定ミス" in message


@pytest.mark.asyncio
async def test_carousel_generation_failure(mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mocker.patch(
        "app.services.publisher.generate_carousel_image",
        side_effect=Exception("rendering failed"),
    )
    sns_mock = mocker.patch("app.services.publisher.publish_to_sns", new=mocker.AsyncMock())
    site_mock = mocker.patch(
        "app.services.publisher.publish_to_site",
        new=mocker.AsyncMock(return_value={"ok": True}),
    )
    notify_mock = mocker.patch("app.services.publisher.notify_slack")

    result = await publisher.publish_article_parallel(staging_supabase, dummy_article)

    sns_mock.assert_not_awaited()  # 画像生成失敗によりSNS投稿はスキップされる
    site_mock.assert_awaited_once()  # サイト公開は継続される

    assert result["sns"]["skipped"] is True
    assert result["site"] == {"ok": True}
    notify_mock.assert_called_once()
