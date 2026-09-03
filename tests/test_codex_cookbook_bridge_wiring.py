import json

import pytest
from fastapi import APIRouter
from starlette.requests import Request

from routes import codex_routes


def _endpoint(router, method: str, path: str):
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.endpoint
    raise AssertionError(f"{method} {path} route not found")


def _request(method: str, path: str, scopes: list[str]) -> Request:
    request = Request({
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "state": {},
    })
    request.state.current_user = "api"
    request.state.api_token = True
    request.state.api_token_owner = "alice"
    request.state.api_token_scopes = scopes
    return request


def _cookbook_router(calls: list[dict]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/model/cached")
    async def model_cached(
        request: Request,
        host=None,
        model_dir=None,
        ssh_port=None,
        platform=None,
    ):
        calls.append({
            "kind": "cached",
            "owner": request.state.current_user,
            "api_token": request.state.api_token,
            "host": host,
            "model_dir": model_dir,
            "ssh_port": ssh_port,
            "platform": platform,
        })
        return {"models": [{"repo_id": "org/model"}]}

    @router.post("/api/model/serve")
    async def model_serve(request: Request, req):
        calls.append({
            "kind": "serve",
            "owner": request.state.current_user,
            "api_token": request.state.api_token,
            "repo_id": req.repo_id,
            "cmd": req.cmd,
        })
        return {"ok": True, "session_id": "serve-test"}

    return router


@pytest.mark.asyncio
async def test_cached_models_uses_injected_cookbook_router_as_token_owner():
    calls = []
    router = codex_routes.setup_codex_routes(
        cookbook_router=_cookbook_router(calls),
    )
    request = _request("GET", "/api/codex/cookbook/cached", ["cookbook:read"])

    result = await _endpoint(router, "GET", "/api/codex/cookbook/cached")(
        request,
        host=None,
    )

    assert result == {"models": [{"repo_id": "org/model"}]}
    assert calls == [{
        "kind": "cached",
        "owner": "alice",
        "api_token": False,
        "host": None,
        "model_dir": None,
        "ssh_port": None,
        "platform": None,
    }]
    assert request.state.current_user == "api"
    assert request.state.api_token is True


@pytest.mark.asyncio
async def test_direct_serve_uses_injected_cookbook_router_as_token_owner():
    calls = []
    router = codex_routes.setup_codex_routes(
        cookbook_router=_cookbook_router(calls),
    )
    request = _request("POST", "/api/codex/cookbook/serve", ["cookbook:launch"])

    result = await _endpoint(router, "POST", "/api/codex/cookbook/serve")(
        request,
        {"repo_id": "org/model", "cmd": "llama-server --port 8000"},
    )

    assert result == {"ok": True, "session_id": "serve-test"}
    assert calls == [{
        "kind": "serve",
        "owner": "alice",
        "api_token": False,
        "repo_id": "org/model",
        "cmd": "llama-server --port 8000",
    }]
    assert request.state.current_user == "api"
    assert request.state.api_token is True


@pytest.mark.asyncio
async def test_saved_preset_uses_injected_cookbook_router_as_token_owner(
    monkeypatch,
    tmp_path,
):
    state_path = tmp_path / "cookbook_state.json"
    state_path.write_text(json.dumps({
        "presets": [{
            "name": "known-good",
            "model": "org/model",
            "cmd": "llama-server --port 8000",
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(codex_routes, "COOKBOOK_STATE_FILE", str(state_path))
    calls = []
    router = codex_routes.setup_codex_routes(
        cookbook_router=_cookbook_router(calls),
    )
    request = _request(
        "POST",
        "/api/codex/cookbook/preset/known-good",
        ["cookbook:launch"],
    )

    result = await _endpoint(
        router,
        "POST",
        "/api/codex/cookbook/preset/{name}",
    )(request, "known-good")

    assert result == {"ok": True, "session_id": "serve-test"}
    assert calls == [{
        "kind": "serve",
        "owner": "alice",
        "api_token": False,
        "repo_id": "org/model",
        "cmd": "llama-server --port 8000",
    }]
