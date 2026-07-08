import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import articles, monitor, newsletter, pipeline, webhook

app = FastAPI(title="Create Authority")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://create-authority.vercel.app",
        "https://create-authority-gcu4t08rn-kassamassas-projects.vercel.app",
        "http://localhost:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipeline.router)
app.include_router(articles.router)
app.include_router(newsletter.router)
app.include_router(monitor.router)
app.include_router(webhook.router)


@app.get("/")
def root():
    return {"service": "create-authority", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/pipeline/debug")
def pipeline_debug():
    """環境変数の設定状況を返す。DB依存なしで常に200を返す。"""
    return {
        "supabase_url": bool(os.getenv("SUPABASE_URL")),
        "supabase_key": bool(os.getenv("SUPABASE_KEY")),
        "dify_api_key": bool(os.getenv("DIFY_API_KEY")),
        "newsapi_key": bool(os.getenv("NEWSAPI_KEY")),
    }


@app.get("/routes")
def list_routes():
    """登録済み全エンドポイントの一覧を返す。デプロイ確認用。"""
    return [
        {"path": route.path, "methods": sorted(route.methods)}
        for route in app.routes
        if hasattr(route, "methods")
    ]
