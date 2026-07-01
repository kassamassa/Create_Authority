import os

import httpx
from dotenv import load_dotenv

load_dotenv()

DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_WORKFLOW_URL = os.getenv("DIFY_WORKFLOW_URL", "https://api.dify.ai/v1/workflows/run")
REQUEST_TIMEOUT = 30.0


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


def summarize_article(title: str, content: str) -> dict:
    outputs = call_workflow({"title": title, "content": content})
    return {
        "summary": outputs.get("summary", ""),
        "category": outputs.get("category"),
        "tags": outputs.get("tags", []),
    }
