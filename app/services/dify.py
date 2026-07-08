import os
import uuid
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

from app.services.publisher import notify_slack

load_dotenv()

DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_WORKFLOW_URL = os.getenv("DIFY_WORKFLOW_URL", "https://api.dify.ai/v1/workflows/run")
REQUEST_TIMEOUT = 30.0
DIFY_PROCESSING_TIMEOUT = 1800.0  # 30分
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "temp")


class DifyConfigError(Exception):
    """4xx系の設定ミスなど、リトライ対象外のエラー"""


class DifyTemporaryError(Exception):
    """5xx・タイムアウトなど、リトライ対象の一時障害"""


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }


def call_workflow(inputs: dict, user: str = "create-authority") -> dict:
    payload = {
        "inputs": inputs,
        "response_mode": "blocking",
        "user": user,
    }
    response = httpx.post(
        DIFY_WORKFLOW_URL,
        json=payload,
        headers=_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("data", {}).get("outputs", {})


def translate_to_japanese(text: str) -> str:
    if not text:
        return ""
    outputs = call_workflow({"text": text, "target_language": "ja"})
    return outputs.get("translated_text", text)


def upload_temp_file(supabase_client, content: str) -> str:
    path = f"temp/{uuid.uuid4()}.txt"
    supabase_client.storage.from_(STORAGE_BUCKET).upload(
        path, (content or "").encode("utf-8"), {"content-type": "text/plain"}
    )
    return path


def delete_temp_file(supabase_client, path: str) -> None:
    supabase_client.storage.from_(STORAGE_BUCKET).remove([path])


def call_dify_workflow(content: str, article_id: str, category: str) -> dict:
    payload = {
        "inputs": {"content": content, "article_id": article_id, "category": category},
        "response_mode": "blocking",
        "user": "create-authority",
    }
    try:
        response = httpx.post(
            DIFY_WORKFLOW_URL,
            json=payload,
            headers=_headers(),
            timeout=DIFY_PROCESSING_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise DifyTemporaryError(str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status >= 500:
            raise DifyTemporaryError(str(exc)) from exc
        raise DifyConfigError(str(exc)) from exc

    data = response.json()
    outputs = data.get("data", {}).get("outputs", {})
    return {
        "summary": outputs.get("summary", ""),
        "faq": outputs.get("faq"),
        "category": outputs.get("category"),
    }


def _reject_article(supabase_client, article_id: str, reason: str) -> None:
    supabase_client.table("articles").update({"status": "rejected"}).eq("id", article_id).execute()
    notify_slack(reason)


def process_article(supabase_client, article: dict) -> dict:
    """ステップ③: articles.content をDifyに直接テキストとして渡し、summary/FAQ/categoryを取得する。"""
    article_id = article["id"]
    content = article.get("content") or ""
    supabase_client.table("articles").update({"status": "processing"}).eq("id", article_id).execute()

    try:
        result = call_dify_workflow(content, article_id, article.get("category") or "未分類")
    except DifyTemporaryError as exc:
        _reject_article(supabase_client, article_id, f"[dify] 一時障害によりrejected: article_id={article_id}: {exc}")
        raise
    except DifyConfigError as exc:
        _reject_article(supabase_client, article_id, f"[dify] 設定ミスによりrejected: article_id={article_id}: {exc}")
        raise

    if not result.get("summary"):
        _reject_article(supabase_client, article_id, f"[dify] summary未生成によりrejected: article_id={article_id}")
        raise DifyConfigError("summaryが生成されませんでした")

    if not result.get("faq"):
        _reject_article(supabase_client, article_id, f"[dify] FAQ未生成によりrejected: article_id={article_id}")
        raise DifyConfigError("FAQが生成されませんでした")

    now = datetime.now(timezone.utc).isoformat()
    metadata = {**(article.get("metadata") or {}), "faq": result["faq"]}
    updated = (
        supabase_client.table("articles")
        .update({
            "summary": result["summary"],
            "category": result.get("category") or article.get("category") or "未分類",
            "metadata": metadata,
            "status": "processed",
            "processed_at": now,
        })
        .eq("id", article_id)
        .execute()
    )
    return updated.data[0] if updated.data else None
