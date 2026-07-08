#!/usr/bin/env python3
"""
収集パイプラインの手動実行スクリプト。
使用方法: python scripts/run_pipeline.py

必要な環境変数（.env または Railway 環境変数）:
  SUPABASE_URL, SUPABASE_KEY, DIFY_API_KEY, DIFY_WORKFLOW_URL
  NEWSAPI_KEY（省略可 — 未設定時は NewsAPI をスキップ）
"""
import asyncio
import os
import sys

# プロジェクトルートを PYTHONPATH に追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_supabase_client
from app.services import collector, dify


def _print_section(title: str) -> None:
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


async def main() -> None:
    print("Create Authority — パイプライン手動実行")
    db = get_supabase_client()

    # ① RSS 収集
    _print_section("STEP 1/4: RSS フィード収集")
    rss_articles, rss_errors = collector.collect_all_rss()
    print(f"収集件数: {len(rss_articles)} 件")
    for err in rss_errors:
        print(f"  [ERROR] {err['source']}: {err['error']}")

    # ② NewsAPI 収集
    _print_section("STEP 2/4: NewsAPI 収集")
    if not os.getenv("NEWSAPI_KEY"):
        print("NEWSAPI_KEY が未設定のためスキップします")
        news_articles: list[dict] = []
    else:
        news_articles, news_errors = await collector.collect_all_newsapi()
        print(f"収集件数: {len(news_articles)} 件")
        for err in news_errors:
            print(f"  [ERROR] {err['source']}: {err['error']}")

    all_articles = rss_articles + news_articles
    print(f"\n合計収集: {len(all_articles)} 件")

    # ③ Supabase 保存
    _print_section("STEP 3/4: Supabase 保存（重複スキップ）")
    saved: list[dict] = []
    for article in all_articles:
        article.setdefault("category", "uncategorized")
        article.setdefault("difficulty", "中")
        result = collector.save_article(db, article)
        if result:
            saved.append(result)
            title_short = (article.get("title") or "")[:60]
            print(f"  [保存] {title_short}")
    print(f"\n保存: {len(saved)} 件 / スキップ(重複): {len(all_articles) - len(saved)} 件")

    if not saved:
        print("\n新規保存記事がないため Dify 処理をスキップします。")
        _print_result(all_articles, saved, [], [])
        return

    # ④ Dify 処理
    _print_section("STEP 4/4: Dify 処理（summary / FAQ / カテゴリ生成）")
    processed: list[dict] = []
    failed: list[dict] = []
    for article in saved:
        title_short = (article.get("title") or "")[:50]
        print(f"  処理中: {title_short}...")
        try:
            result = dify.process_article(db, article)
            processed.append(result)
            summary_short = (result.get("summary") or "")[:60] if result else ""
            print(f"    → 完了 | summary: {summary_short}")
        except Exception as exc:
            failed.append({"article_id": article.get("id"), "error": str(exc)})
            print(f"    → [ERROR] {exc}")

    _print_result(all_articles, saved, processed, failed)


def _print_result(
    all_articles: list,
    saved: list,
    processed: list,
    failed: list,
) -> None:
    _print_section("結果サマリー")
    print(f"  収集    : {len(all_articles)} 件")
    print(f"  保存    : {len(saved)} 件")
    print(f"  Dify 成功: {len(processed)} 件")
    print(f"  Dify 失敗: {len(failed)} 件")
    if failed:
        print("\n  失敗した記事:")
        for f in failed:
            print(f"    - article_id={f['article_id']}: {f['error']}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
