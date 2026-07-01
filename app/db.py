import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


@lru_cache
def get_supabase_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY が設定されていません")
    return create_client(url, key)


def get_db() -> Client:
    """FastAPIの依存性注入用。テストではapp.dependency_overridesで差し替える。"""
    return get_supabase_client()
