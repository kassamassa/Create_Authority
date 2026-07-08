import os
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

_router_errors: dict = {}

def _include(name: str, module_path: str, attr: str = "router"):
    try:
        import importlib
        mod = importlib.import_module(module_path)
        app.include_router(getattr(mod, attr))
        print(f"[startup] {name} router registered OK")
    except Exception as exc:
        _router_errors[name] = f"{type(exc).__name__}: {exc}"
        print(f"[startup] {name} router FAILED: {exc}")
        traceback.print_exc()

_include("pipeline",     "app.routers.pipeline")
_include("articles",     "app.routers.articles")
_include("newsletter",   "app.routers.newsletter")
_include("monitor",      "app.routers.monitor")
_include("webhook",      "app.routers.webhook")


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
    """登録済み全エンドポイントの一覧と、router 登録エラーを返す。デプロイ確認用。"""
    return {
        "routes": [
            {"path": route.path, "methods": sorted(route.methods)}
            for route in app.routes
            if hasattr(route, "methods")
        ],
        "router_errors": _router_errors,
    }
