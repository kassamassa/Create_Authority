import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.services import archiver, collector, dify, publisher

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)


@router.post("/collect/test")
async def test_collect():
    """収集パイプラインの疎通確認。RSS取得とSupabase接続を個別にテストし、必ず200を返す。"""
    results = {}

    # Step 1: RSS フィード 1 件テスト（httpx 不使用 — feedparser が直接取得）
    try:
        import feedparser
        feed = feedparser.parse(
            "https://rss.itmedia.co.jp/rss/2.0/itmedia_all.xml"
        )
        results["rss"] = {
            "status": "ok",
            "entries": len(feed.entries),
            "first_title": feed.entries[0].title if feed.entries else None,
        }
    except Exception as exc:
        results["rss"] = {"status": "error", "detail": str(exc)}

    # Step 2: Supabase 接続テスト（SELECT）
    try:
        from app.db import get_supabase_client
        db = get_supabase_client()
        res = db.table("articles").select("id").limit(1).execute()
        results["supabase_select"] = {"status": "ok", "rows": len(res.data)}
    except Exception as exc:
        results["supabase_select"] = {"status": "error", "detail": str(exc)}

    # Step 3: Supabase INSERT テスト（実際に1件書き込む）
    try:
        import uuid
        from app.db import get_supabase_client
        db = get_supabase_client()
        test_id = str(uuid.uuid4())
        test_article = {
            "id": test_id,
            "title": "テスト記事",
            "content": "テスト本文",
            "category": "属人化解消",
            "difficulty": "低",
            "source_url": f"https://test.example.com/{uuid.uuid4()}",
            "source_type": "rss",
            "status": "collected",
        }
        res = db.table("articles").insert(test_article).execute()
        if res.data:
            results["supabase_insert"] = {"status": "ok", "id": res.data[0].get("id")}
            # テストデータを削除
            db.table("articles").delete().eq("id", test_id).execute()
        else:
            results["supabase_insert"] = {
                "status": "error",
                "detail": "data が空（RLSブロックまたはスキーマ不一致の可能性）",
                "raw": str(res),
            }
    except Exception as exc:
        results["supabase_insert"] = {"status": "error", "detail": str(exc)}

    return results


@router.post("/collect/debug")
async def debug_collect():
    """RSS1件を実際にinsertして詳細な結果をレスポンスに返す。"""
    import feedparser
    import uuid
    from app.db import get_supabase_client

    # RSS 1件取得
    feed = feedparser.parse(
        "https://rss.itmedia.co.jp/rss/2.0/itmedia_all.xml"
    )
    entry = feed.entries[0]

    # 実際の save_article と同じデータ構造で作成
    article = {
        "id": str(uuid.uuid4()),
        "title": entry.get("title", ""),
        "content": entry.get("summary", ""),
        "category": "未分類",
        "difficulty": "低",
        "source_url": entry.get("link", ""),
        "source_type": "rss",
        "status": "collected",
    }

    # INSERT を試みる
    try:
        db = get_supabase_client()
        res = db.table("articles").insert(article).execute()
        return {
            "article": article,
            "insert_result": {
                "data": res.data,
                "count": res.count,
            },
        }
    except Exception as exc:
        return {
            "article": article,
            "insert_error": str(exc),
        }


@router.post("/collect")
async def run_collect(
    feed_url: Optional[str] = None,
    skip_dify: bool = False,
    db=Depends(get_db),
):
    """RSS・NewsAPIから記事を収集し、Difyで処理する。
    feed_url を指定すると指定フィードのみ収集。省略すると全ソースを収集。
    skip_dify=true にすると収集・保存のみ行いDify処理をスキップ（デバッグ用）。
    """
    logger.info("[collect] 開始 feed_url=%s skip_dify=%s", feed_url, skip_dify)

    all_articles: list[dict] = []
    errors: list[dict] = []

    # ① 収集
    try:
        if feed_url:
            logger.info("[collect] RSS収集（単体）: %s", feed_url)
            try:
                articles = collector.collect_from_rss(feed_url)
                all_articles.extend(articles)
                logger.info("[collect] RSS収集完了: %d 件", len(articles))
            except Exception as exc:
                logger.error("[collect] RSS収集エラー: %s — %s", feed_url, exc)
                errors.append({"source": feed_url, "error": str(exc)})
        else:
            logger.info("[collect] 全RSS収集開始 (%d フィード)", len(collector.RSS_FEEDS))
            rss_articles, rss_errors = collector.collect_all_rss()
            all_articles.extend(rss_articles)
            errors.extend(rss_errors)
            logger.info("[collect] RSS収集完了: %d 件, エラー: %d 件", len(rss_articles), len(rss_errors))

            logger.info("[collect] NewsAPI収集開始")
            news_articles, news_errors = await collector.collect_all_newsapi()
            all_articles.extend(news_articles)
            errors.extend(news_errors)
            logger.info("[collect] NewsAPI収集完了: %d 件, エラー: %d 件", len(news_articles), len(news_errors))

    except Exception as exc:
        logger.exception("[collect] 収集ステップで予期しないエラー: %s", exc)
        errors.append({"source": "collect_step", "error": str(exc)})

    logger.info("[collect] 合計収集: %d 件", len(all_articles))

    # ② DX キーワードフィルタリング + Supabase 保存
    skipped_count = 0
    saved: list[dict] = []
    save_errors: list[dict] = []
    for article in all_articles:
        if not collector.is_dx_related(article):
            skipped_count += 1
            logger.debug("[collect] DXキーワード不一致スキップ: %s", (article.get("title") or "")[:60])
            continue
        article.setdefault("category", "未分類")
        article.setdefault("difficulty", "低")
        try:
            result = collector.save_article(db, article)
            if result:
                saved.append(result)
        except Exception as exc:
            url_short = (article.get("source_url") or "")[:80]
            logger.error("[collect] save_article エラー url=%s: %s", url_short, exc)
            save_errors.append({"source_url": url_short, "error": str(exc)})

    errors.extend(save_errors)
    logger.info("[collect] 保存完了: %d 件 (DXフィルタースキップ %d 件, エラー %d 件)",
                len(saved), skipped_count, len(save_errors))

    if skip_dify:
        logger.info("[collect] skip_dify=true のためDify処理をスキップ")
        return {
            "collected": len(all_articles),
            "skipped_dx_filter": skipped_count,
            "saved": len(saved),
            "processed": 0,
            "skipped_dify": True,
            "errors": errors,
        }

    # ③ Dify 処理
    processed: list[dict] = []
    dify_errors: list[dict] = []
    for article in saved:
        article_id = article.get("id", "")
        title_short = (article.get("title") or "")[:50]
        logger.info("[collect] Dify処理開始 id=%s title=%s", article_id, title_short)
        try:
            result = dify.process_article(db, article)
            if result:
                processed.append(result)
                logger.info("[collect] Dify処理完了 id=%s", article_id)
        except Exception as exc:
            logger.error("[collect] Dify処理エラー id=%s: %s", article_id, exc)
            dify_errors.append({"article_id": article_id, "error": str(exc)})

    errors.extend(dify_errors)
    logger.info("[collect] 完了: collected=%d saved=%d processed=%d errors=%d",
                len(all_articles), len(saved), len(processed), len(errors))

    return {
        "collected": len(all_articles),
        "skipped_dx_filter": skipped_count,
        "saved": len(saved),
        "processed": len(processed),
        "errors": errors,
    }


@router.post("/collect/youtube/{video_id}")
def run_collect_youtube(video_id: str, db=Depends(get_db)):
    """YouTube動画の字幕を収集してDifyで処理する。"""
    logger.info("[collect/youtube] video_id=%s", video_id)
    transcript = collector.collect_youtube_transcript(video_id)
    if transcript is None:
        raise HTTPException(
            status_code=404,
            detail="字幕が見つかりません（非公開・字幕無効・非対応言語）",
        )

    article = {
        "title": f"YouTube: {video_id}",
        "content": transcript,
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "source_type": "youtube",
        "category": "uncategorized",
        "difficulty": "中",
    }
    try:
        saved = collector.save_article(db, article)
    except Exception as exc:
        logger.error("[collect/youtube] save_article エラー: %s", exc)
        raise HTTPException(status_code=502, detail=f"保存に失敗しました: {exc}")

    if not saved:
        return {"message": "既に保存済みです", "saved": 0, "processed": 0}

    try:
        result = dify.process_article(db, saved)
        return {"collected": 1, "saved": 1, "processed": 1, "article": result}
    except Exception as exc:
        logger.error("[collect/youtube] Dify処理エラー: %s", exc)
        return {"collected": 1, "saved": 1, "processed": 0, "error": str(exc)}


@router.post("/process/test")
def test_process():
    """status=collected の記事を1件取得し、articles.content をDifyに渡して結果を返す。
    注意: タイムアウトを25秒に制限しているため、Dify処理が長い場合はタイムアウトエラーになる。
    その場合は /pipeline/dify/raw を使うこと。
    """
    import os
    import httpx as _httpx
    from app.db import get_supabase_client
    from app.services import dify as dify_svc

    DEBUG_TIMEOUT = 25.0  # Railway HTTP タイムアウト(30s)より短く設定

    results: dict = {}

    # Step 1: 環境変数確認
    results["env"] = {
        "DIFY_API_KEY": bool(os.getenv("DIFY_API_KEY")),
        "DIFY_WORKFLOW_URL": os.getenv("DIFY_WORKFLOW_URL") or "(未設定・デフォルト使用)",
    }

    # Step 2: status=collected の記事を取得
    try:
        db = get_supabase_client()
        res = db.table("articles").select("*").eq("status", "collected").limit(1).execute()
        if not res.data:
            results["error"] = "status=collected の記事が見つかりません。先に /pipeline/collect?skip_dify=true を実行してください"
            return results
        article = res.data[0]
        results["article"] = {
            "id": article["id"],
            "title": (article.get("title") or "")[:60],
            "content_length": len(article.get("content") or ""),
        }
    except Exception as exc:
        results["fetch_error"] = str(exc)
        return results

    # Step 3: Difyに送るペイロードを記録（Dify呼び出し前に必ず設定）
    content = article.get("content") or ""
    article_id = article["id"]
    category = article.get("category") or "未分類"
    results["dify_payload_sent"] = {
        "content_length": len(content),
        "content_preview": content[:100],
        "article_id": article_id,
        "category": category,
    }

    # Step 4a: 生レスポンス記録（outputs.result の中身を確認）
    try:
        payload = {
            "inputs": {"content": content, "article_id": article_id, "category": category},
            "response_mode": "blocking",
            "user": "create-authority",
        }
        raw_response = _httpx.post(
            dify_svc.DIFY_WORKFLOW_URL,
            json=payload,
            headers=dify_svc._headers(),
            timeout=DEBUG_TIMEOUT,
        )
        raw_json = raw_response.json()
        outputs = raw_json.get("data", {}).get("outputs", {})
        results["dify_raw"] = {
            "status_code": raw_response.status_code,
            "outputs_keys": list(outputs.keys()),
            "result_preview": (outputs.get("result") or "")[:200],
            "summary_direct": outputs.get("summary"),
        }
    except _httpx.TimeoutException:
        results["dify_raw"] = {"status": "timeout"}
    except Exception as exc:
        results["dify_raw"] = {"status": "error", "detail": str(exc)}

    # Step 4b: call_dify_workflow（Markdownパース込み）の戻り値を確認
    try:
        dify_svc.DIFY_PROCESSING_TIMEOUT = DEBUG_TIMEOUT  # テスト用に短縮
        call_result = dify_svc.call_dify_workflow(content, article_id, category)
        results["call_dify_result"] = call_result
    except _httpx.TimeoutException:
        results["call_dify_result"] = {"status": "timeout"}
    except Exception as exc:
        results["call_dify_result"] = {"status": "error", "detail": str(exc)}

    return results


@router.post("/dify/raw")
def dify_raw():
    """status=collected の記事を1件取得し、Dify APIへのリクエスト/レスポンスをそのまま返す最小テスト。"""
    import os
    import httpx as _httpx
    from app.db import get_supabase_client
    from app.services import dify as dify_svc

    # DB から記事取得
    try:
        db = get_supabase_client()
        res = db.table("articles").select("id, content, category").eq("status", "collected").limit(1).execute()
        if not res.data:
            return {"error": "status=collected の記事が見つかりません"}
        article = res.data[0]
    except Exception as exc:
        return {"db_error": str(exc)}

    content = (article.get("content") or "")[:500]
    article_id = article["id"]

    payload = {
        "inputs": {
            "content": content,
            "article_id": article_id,
            "category": "属人化解消",
        },
        "response_mode": "blocking",
        "user": "debug",
    }

    try:
        response = _httpx.post(
            dify_svc.DIFY_WORKFLOW_URL,
            json=payload,
            headers=dify_svc._headers(),
            timeout=25.0,
        )
        return {
            "payload_sent": payload,
            "status_code": response.status_code,
            "response_body": response.json(),
        }
    except _httpx.TimeoutException:
        return {
            "payload_sent": payload,
            "error": "timeout after 25s",
        }
    except Exception as exc:
        return {
            "payload_sent": payload,
            "error": str(exc),
        }


@router.post("/process/all")
def run_process_all(db=Depends(get_db)):
    """status=collected の記事を全件取得し、Dify処理を順次実行する。"""
    res = db.table("articles").select("*").eq("status", "collected").execute()
    articles = res.data or []
    total = len(articles)
    logger.info("[process/all] 開始: %d 件", total)

    processed_ids: list[str] = []
    rejected_ids: list[str] = []
    errors: list[dict] = []

    for article in articles:
        article_id = article.get("id", "")
        title_short = (article.get("title") or "")[:50]
        logger.info("[process/all] 処理中 id=%s title=%s", article_id, title_short)
        try:
            result = dify.process_article(db, article)
            if result:
                processed_ids.append(article_id)
                logger.info("[process/all] 完了 id=%s", article_id)
            else:
                rejected_ids.append(article_id)
        except Exception as exc:
            logger.error("[process/all] エラー id=%s: %s", article_id, exc)
            errors.append({"article_id": article_id, "error": str(exc)})
            rejected_ids.append(article_id)

    logger.info(
        "[process/all] 完了: total=%d processed=%d rejected=%d errors=%d",
        total, len(processed_ids), len(rejected_ids), len(errors),
    )
    return {
        "total": total,
        "processed": len(processed_ids),
        "rejected": len(rejected_ids),
        "errors": errors,
    }


@router.post("/process/{article_id}")
def run_process(article_id: str, db=Depends(get_db)):
    logger.info("[process] article_id=%s", article_id)
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")
    return dify.process_article(db, result.data[0])


@router.post("/publish/{article_id}")
async def run_publish(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")
    return await publisher.publish_article_parallel(db, result.data[0])


@router.post("/archive/{article_id}")
def run_archive(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    try:
        return archiver.archive_article(db, result.data[0])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHubアーカイブに失敗しました: {exc}")
