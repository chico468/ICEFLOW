from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from src.api import main


def test_resolve_cors_dev_with_no_list(monkeypatch):
    assert main.resolve_cors_origins({"ICEFLOW_ENV": "dev"}) == ["*"]


def test_resolve_cors_explicit_list_trim_ignores_empties(monkeypatch):
    origins = main.resolve_cors_origins({"ICEFLOW_CORS_ORIGINS": " https://a.com , , https://b.com "})
    assert origins == ["https://a.com", "https://b.com"]


def test_resolve_cors_neither_set(monkeypatch):
    assert main.resolve_cors_origins({}) is None


def test_cors_headers_with_origin_on_get(monkeypatch):
    app = FastAPI()
    origins = main.resolve_cors_origins({"ICEFLOW_CORS_ORIGINS": "https://app.example.com"})
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health():
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/api/v1/health", headers={"Origin": "https://app.example.com"})
    assert resp.headers.get("access-control-allow-origin") == "https://app.example.com"
    # Preflight to route that allows method
    preflight = client.options("/api/v1/health", headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "GET"})
    assert preflight.status_code in (200, 204)
    assert preflight.headers.get("access-control-allow-origin") == "https://app.example.com"
