import os

import httpx
import pytest

from app.services import dify
from app.services.publisher import SIGNED_URL_EXPIRES_IN, generate_signed_url

REQUIRED_DIFY_ENV = ("DIFY_API_KEY", "DIFY_WORKFLOW_URL")


def _dify_configured() -> bool:
    return all(os.getenv(name) for name in REQUIRED_DIFY_ENV)


def _insert_dummy_article(staging_supabase, dummy_article):
    staging_supabase.table("articles").insert(dummy_article).execute()
    staging_supabase.created_article_ids.append(dummy_article["id"])


@pytest.fixture
def mock_storage(mocker, staging_supabase):
    """Supabase Storageへの実アクセスを避け、ロジックのみをテストするためのモック。

    supabase-py/storage3のバージョンによってstorageプロパティのインスタンス
    キャッシュ挙動が異なる可能性があるため、インスタンス属性ではなく
    SyncStorageClient.from_をクラスレベルでパッチし、確実に差し替える。
    """
    bucket = mocker.MagicMock()
    bucket.upload.return_value = {"path": "temp/mock.txt", "Key": "temp/mock.txt"}
    bucket.create_signed_url.return_value = {"signedURL": "https://example.com/signed"}
    bucket.remove.return_value = []
    mocker.patch("storage3._sync.client.SyncStorageClient.from_", return_value=bucket)
    return bucket


# --- translate_to_japanese（既存機能） ---

def test_translate_to_japanese_empty_string_returns_empty():
    assert dify.translate_to_japanese("") == ""


def test_call_workflow_success(mocker):
    mock_response = mocker.Mock()
    mock_response.json.return_value = {"data": {"outputs": {"translated_text": "こんにちは"}}}
    mock_response.raise_for_status.return_value = None
    mocker.patch("httpx.post", return_value=mock_response)

    result = dify.translate_to_japanese("hello")
    assert result == "こんにちは"


# --- 正常系 ---

def test_signed_url_generation(mock_storage, staging_supabase):
    content = "本文サンプルテキストです。"
    path = dify.upload_temp_file(staging_supabase, content)

    assert path.startswith("temp/")
    assert path.endswith(".txt")
    mock_storage.upload.assert_called_once()

    signed_url = generate_signed_url(staging_supabase, dify.STORAGE_BUCKET, path, SIGNED_URL_EXPIRES_IN)
    assert signed_url == "https://example.com/signed"
    # 有効期限1800秒(30分)で発行依頼していることを確認する
    mock_storage.create_signed_url.assert_called_once_with(path, SIGNED_URL_EXPIRES_IN)
    assert SIGNED_URL_EXPIRES_IN == 1800

    dify.delete_temp_file(staging_supabase, path)
    mock_storage.remove.assert_called_once_with([path])


def test_dify_processing(mock_storage, mocker, staging_supabase, dummy_article):
    # DIFY_API_KEYがdummy値だと実際のDify APIが401を返すため、
    # Dify呼び出し自体はモックし、DB永続化のロジックを検証する。
    mocker.patch(
        "app.services.dify.call_dify_workflow",
        return_value={
            "summary": "テスト要約",
            "faq": [
                {"q": "質問1", "a": "回答1"},
                {"q": "質問2", "a": "回答2"},
            ],
            "category": "属人化解消",
        },
    )

    _insert_dummy_article(staging_supabase, dummy_article)

    dify.process_article(staging_supabase, dummy_article)

    result = staging_supabase.table("articles").select("*").eq("id", dummy_article["id"]).execute()
    article = result.data[0]
    assert article["summary"] == "テスト要約"
    assert article["category"] == "属人化解消"
    assert article["status"] == "processed"


def test_temp_file_deletion(mock_storage, mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mocker.patch(
        "app.services.dify.call_dify_workflow",
        return_value={"summary": "要約", "faq": [{"q": "質問", "a": "回答"}], "category": "manufacturing"},
    )

    dify.process_article(staging_supabase, dummy_article)

    mock_storage.remove.assert_called_once()


def test_temp_file_deletion_on_failure(mock_storage, mocker, staging_supabase, dummy_article):
    """finallyブロックにより、異常系でもtempファイルが必ず削除されることを確認する。"""
    _insert_dummy_article(staging_supabase, dummy_article)

    mocker.patch(
        "app.services.dify.call_dify_workflow",
        side_effect=dify.DifyTemporaryError("timeout"),
    )
    mocker.patch("app.services.dify.notify_slack")

    with pytest.raises(dify.DifyTemporaryError):
        dify.process_article(staging_supabase, dummy_article)

    mock_storage.remove.assert_called_once()


# --- 異常系（pytest-mockでモック） ---

def test_dify_timeout(mock_storage, mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mocker.patch("app.services.dify.httpx.post", side_effect=httpx.TimeoutException("timeout"))
    notify_mock = mocker.patch("app.services.dify.notify_slack")

    with pytest.raises(dify.DifyTemporaryError):
        dify.process_article(staging_supabase, dummy_article)

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "rejected"

    mock_storage.remove.assert_called_once()
    notify_mock.assert_called_once()


def test_signed_url_expired(mock_storage, mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mock_request = mocker.Mock()
    mock_response = mocker.Mock()
    mock_response.status_code = 403
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403 Forbidden", request=mock_request, response=mock_response
    )
    mocker.patch("app.services.dify.httpx.post", return_value=mock_response)
    notify_mock = mocker.patch("app.services.dify.notify_slack")

    with pytest.raises(dify.DifyConfigError):
        dify.process_article(staging_supabase, dummy_article)

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "rejected"

    mock_storage.remove.assert_called_once()
    notify_mock.assert_called_once()
    message = notify_mock.call_args[0][0]
    assert "設定ミス" in message


def test_faq_not_generated(mock_storage, staging_supabase, dummy_article):
    if not _dify_configured():
        pytest.skip("DIFY_API_KEY / DIFY_WORKFLOW_URL が未設定のためスキップ")

    _insert_dummy_article(staging_supabase, dummy_article)

    with pytest.raises(dify.DifyConfigError):
        dify.process_article(staging_supabase, dummy_article)

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "rejected"
