import base64
import json
import os
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services import dify
from app.services.publisher import SIGNED_URL_EXPIRES_IN, generate_signed_url

REQUIRED_DIFY_ENV = ("DIFY_API_KEY", "DIFY_WORKFLOW_URL")


def _dify_configured() -> bool:
    return all(os.getenv(name) for name in REQUIRED_DIFY_ENV)


def _decode_jwt_exp(token: str) -> int:
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    return payload["exp"]


def _insert_dummy_article(staging_supabase, dummy_article):
    staging_supabase.table("articles").insert(dummy_article).execute()
    staging_supabase.created_article_ids.append(dummy_article["id"])


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


# --- 正常系（実APIを使用） ---

def test_signed_url_generation(staging_supabase):
    content = "本文サンプルテキストです。"
    path = dify.upload_temp_file(staging_supabase, content)

    assert path.startswith("temp/")
    assert path.endswith(".txt")

    signed_url = generate_signed_url(staging_supabase, dify.STORAGE_BUCKET, path, SIGNED_URL_EXPIRES_IN)
    assert signed_url

    token = parse_qs(urlparse(signed_url).query).get("token", [None])[0]
    assert token is not None

    exp = _decode_jwt_exp(token)
    remaining = exp - time.time()
    # 30分(1800秒)前後の許容範囲で発行されていること
    assert 1700 <= remaining <= 1900

    dify.delete_temp_file(staging_supabase, path)


def test_dify_processing(staging_supabase, dummy_article):
    if not _dify_configured():
        pytest.skip("DIFY_API_KEY / DIFY_WORKFLOW_URL が未設定のためスキップ")

    _insert_dummy_article(staging_supabase, dummy_article)

    path = dify.upload_temp_file(staging_supabase, dummy_article["content"])
    try:
        signed_url = generate_signed_url(staging_supabase, dify.STORAGE_BUCKET, path, SIGNED_URL_EXPIRES_IN)
        result = dify.call_dify_workflow(signed_url, dummy_article["id"], dummy_article["category"])

        assert result["summary"]
        assert result["faq"]
        assert result["category"]
    finally:
        dify.delete_temp_file(staging_supabase, path)


def test_temp_file_deletion(mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mocker.patch(
        "app.services.dify.call_dify_workflow",
        return_value={"summary": "要約", "faq": [{"q": "質問", "a": "回答"}], "category": "manufacturing"},
    )
    upload_spy = mocker.spy(dify, "upload_temp_file")

    dify.process_article(staging_supabase, dummy_article)

    temp_path = upload_spy.spy_return
    with pytest.raises(Exception):
        staging_supabase.storage.from_(dify.STORAGE_BUCKET).download(temp_path)


def test_temp_file_deletion_on_failure(mocker, staging_supabase, dummy_article):
    """finallyブロックにより、異常系でもtempファイルが必ず削除されることを確認する。"""
    _insert_dummy_article(staging_supabase, dummy_article)

    mocker.patch(
        "app.services.dify.call_dify_workflow",
        side_effect=dify.DifyTemporaryError("timeout"),
    )
    mocker.patch("app.services.dify.notify_slack")
    upload_spy = mocker.spy(dify, "upload_temp_file")

    with pytest.raises(dify.DifyTemporaryError):
        dify.process_article(staging_supabase, dummy_article)

    temp_path = upload_spy.spy_return
    with pytest.raises(Exception):
        staging_supabase.storage.from_(dify.STORAGE_BUCKET).download(temp_path)


# --- 異常系（pytest-mockでモック） ---

def test_dify_timeout(mocker, staging_supabase, dummy_article):
    _insert_dummy_article(staging_supabase, dummy_article)

    mocker.patch("app.services.dify.httpx.post", side_effect=httpx.TimeoutException("timeout"))
    notify_mock = mocker.patch("app.services.dify.notify_slack")
    upload_spy = mocker.spy(dify, "upload_temp_file")

    with pytest.raises(dify.DifyTemporaryError):
        dify.process_article(staging_supabase, dummy_article)

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "rejected"

    temp_path = upload_spy.spy_return
    with pytest.raises(Exception):
        staging_supabase.storage.from_(dify.STORAGE_BUCKET).download(temp_path)

    notify_mock.assert_called_once()


def test_signed_url_expired(mocker, staging_supabase, dummy_article):
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

    notify_mock.assert_called_once()
    message = notify_mock.call_args[0][0]
    assert "設定ミス" in message


def test_faq_not_generated(staging_supabase, dummy_article):
    if not _dify_configured():
        pytest.skip("DIFY_API_KEY / DIFY_WORKFLOW_URL が未設定のためスキップ")

    _insert_dummy_article(staging_supabase, dummy_article)

    with pytest.raises(dify.DifyConfigError):
        dify.process_article(staging_supabase, dummy_article)

    result = staging_supabase.table("articles").select("status").eq("id", dummy_article["id"]).execute()
    assert result.data[0]["status"] == "rejected"
