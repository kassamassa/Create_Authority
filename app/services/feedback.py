import os

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

VALID_INTENTS = ("interest", "inquiry", "consultation", "other")


def analyze_intent(content: str) -> str:
    """メルマガ還信式返信の本文からClaude APIで意図を分類する。"""
    prompt = (
        "以下はメルマガへの返信メールの本文です。返信者の意図を "
        "interest(興味) / inquiry(質問) / consultation(個別相談希望) / other(その他) "
        "のいずれか1語だけで分類してください。単語のみを出力してください。\n\n"
        f"{content}"
    )
    response = httpx.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 10,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()
    text = data.get("content", [{}])[0].get("text", "").strip().lower()
    return text if text in VALID_INTENTS else "other"
