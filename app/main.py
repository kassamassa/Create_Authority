import os
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# pipeline を先頭で明示的に import
from app.routers.pipeline import router as pipeline_router

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

# ① include_router（標準的な方法）
try:
    app.include_router(pipeline_router)
    print(f"[startup] pipeline include_router OK")
except Exception as exc:
    _router_errors["pipeline_include"] = f"{type(exc).__name__}: {exc}"
    print(f"[startup] pipeline include_router FAILED: {exc}")
    traceback.print_exc()

# ② 直接 routes リストに追加（include_router が機能しない場合のフォールバック）
try:
    for route in pipeline_router.routes:
        if route not in app.router.routes:
            app.router.routes.append(route)
    print(f"[startup] pipeline direct append: {len(pipeline_router.routes)} routes")
except Exception as exc:
    _router_errors["pipeline_direct"] = f"{type(exc).__name__}: {exc}"
    print(f"[startup] pipeline direct FAILED: {exc}")
    traceback.print_exc()


def _safe_include(name: str, import_path: str, attr: str = "router") -> None:
    try:
        import importlib
        mod = importlib.import_module(import_path)
        app.include_router(getattr(mod, attr))
        print(f"[startup] {name} router registered OK")
    except Exception as exc:
        _router_errors[name] = f"{type(exc).__name__}: {exc}"
        print(f"[startup] {name} FAILED: {exc}")
        traceback.print_exc()


_safe_include("articles",   "app.routers.articles")
_safe_include("newsletter", "app.routers.newsletter")
_safe_include("monitor",    "app.routers.monitor")
_safe_include("webhook",    "app.routers.webhook")


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
    """登録済み全エンドポイント・router内ルート・登録エラーを返す。デプロイ確認用。"""
    return {
        "app_routes": [
            {"path": route.path, "methods": sorted(route.methods)}
            for route in app.routes
            if hasattr(route, "methods")
        ],
        "pipeline_routes": [r.path for r in pipeline_router.routes],
        "router_errors": _router_errors,
    }
