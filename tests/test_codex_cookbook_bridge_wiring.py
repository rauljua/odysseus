import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from starlette.requests import Request

from routes import codex_routes
from core.models import ChatMessage
from routes.webhook.webhook_routes import SyncChatRequest


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


def _webhook_router(calls: list[dict]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/chat")
    async def sync_chat(request: Request, body: SyncChatRequest):
        calls.append({
            "owner": request.state.api_token_owner,
            "api_token": request.state.api_token,
            "message": body.message,
            "model": body.model,
            "endpoint_id": body.endpoint_id,
            "max_tokens": body.max_tokens,
        })
        return {
            "response": "pong",
            "session_id": "session-test",
            "model": body.model,
        }

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
async def test_chat_uses_injected_sync_handler_with_chat_scope():
    calls = []
    router = codex_routes.setup_codex_routes(
        webhook_router=_webhook_router(calls),
    )
    request = _request("POST", "/api/codex/chat", ["chat"])
    body = SyncChatRequest(
        message="ping",
        model="org/model",
        endpoint_id="local-test",
        max_tokens=16,
    )

    result = await _endpoint(router, "POST", "/api/codex/chat")(request, body)

    assert result == {
        "response": "pong",
        "session_id": "session-test",
        "model": "org/model",
    }
    assert calls == [{
        "owner": "alice",
        "api_token": True,
        "message": "ping",
        "model": "org/model",
        "endpoint_id": "local-test",
        "max_tokens": 16,
    }]


@pytest.mark.asyncio
async def test_chat_rejects_token_without_chat_scope():
    calls = []
    router = codex_routes.setup_codex_routes(
        webhook_router=_webhook_router(calls),
    )
    request = _request("POST", "/api/codex/chat", ["cookbook:read"])

    with pytest.raises(Exception) as exc_info:
        await _endpoint(router, "POST", "/api/codex/chat")(
            request,
            SyncChatRequest(message="ping"),
        )

    assert getattr(exc_info.value, "status_code", None) == 403
    assert calls == []


def test_chat_history_read_returns_only_requested_owner_session():
    session = SimpleNamespace(
        owner="alice",
        name="Local model debugging",
        model="org/model",
        history=[
            ChatMessage("user", "first"),
            ChatMessage("assistant", "second", {"reasoning": "checked"}),
            ChatMessage("user", "third"),
        ],
    )
    manager = SimpleNamespace(get_session=lambda session_id: session)
    router = codex_routes.setup_codex_routes(session_manager=manager)
    request = _request("GET", "/api/codex/chat/session-test", ["chat:read"])

    result = _endpoint(router, "GET", "/api/codex/chat/{session_id}")(
        request,
        "session-test",
        offset=1,
        limit=1,
    )

    assert result == {
        "session_id": "session-test",
        "name": "Local model debugging",
        "model": "org/model",
        "messages": [{
            "role": "assistant",
            "content": "second",
            "metadata": {"reasoning": "checked"},
        }],
        "total": 3,
        "offset": 1,
        "limit": 1,
    }


@pytest.mark.parametrize("owner,scopes", [
    ("bob", ["chat:read"]),
    ("alice", ["chat"]),
])
def test_chat_history_read_rejects_cross_owner_or_send_only_token(owner, scopes):
    session = SimpleNamespace(owner=owner, history=[])
    manager = SimpleNamespace(get_session=lambda session_id: session)
    router = codex_routes.setup_codex_routes(session_manager=manager)
    request = _request("GET", "/api/codex/chat/session-test", scopes)

    with pytest.raises(Exception) as exc_info:
        _endpoint(router, "GET", "/api/codex/chat/{session_id}")(
            request,
            "session-test",
        )

    expected = 404 if owner == "bob" else 403
    assert getattr(exc_info.value, "status_code", None) == expected


def test_chat_history_read_returns_404_for_missing_session():
    def missing(session_id):
        raise KeyError(session_id)

    manager = SimpleNamespace(get_session=missing)
    router = codex_routes.setup_codex_routes(session_manager=manager)
    request = _request("GET", "/api/codex/chat/missing", ["chat:read"])

    with pytest.raises(Exception) as exc_info:
        _endpoint(router, "GET", "/api/codex/chat/{session_id}")(
            request,
            "missing",
        )

    assert getattr(exc_info.value, "status_code", None) == 404


def test_capabilities_reports_chat_read_separately_from_send():
    manager = SimpleNamespace(get_session=lambda session_id: None)
    router = codex_routes.setup_codex_routes(
        webhook_router=_webhook_router([]),
        session_manager=manager,
    )
    capabilities = _endpoint(router, "GET", "/api/codex/capabilities")

    send_only = capabilities(
        _request("GET", "/api/codex/capabilities", ["chat"]),
    )["tools"]["chat"]
    reader = capabilities(
        _request("GET", "/api/codex/capabilities", ["chat", "chat:read"]),
    )["tools"]["chat"]

    assert send_only["send"] is True
    assert send_only["read"] is False
    assert reader["read"] is True
    assert reader["history_available"] is True
    assert reader["actions"] == ["read", "send"]


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


@pytest.mark.asyncio
async def test_output_recovers_local_log_after_task_record_disappears(
    monkeypatch,
    tmp_path,
):
    state_path = tmp_path / "cookbook_state.json"
    state_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    monkeypatch.setattr(codex_routes, "COOKBOOK_STATE_FILE", str(state_path))
    commands = []

    class _Process:
        returncode = 0

        async def communicate(self):
            return b"root cause from persistent log\n", b""

    async def _create_subprocess_shell(command, **kwargs):
        commands.append(command)
        return _Process()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _create_subprocess_shell)
    router = codex_routes.setup_codex_routes()
    request = _request(
        "GET",
        "/api/codex/cookbook/output/serve-gone",
        ["cookbook:read"],
    )

    result = await _endpoint(
        router,
        "GET",
        "/api/codex/cookbook/output/{session_id}",
    )(request, "serve-gone", tail=600)

    assert result["host"] == "local"
    assert result["task"] is None
    assert result["orphaned"] is True
    assert result["output"] == "root cause from persistent log\n"
    assert commands == [
        "if [ -s /tmp/odysseus-tmux/serve-gone.log ]; then "
        "tail -n 600 /tmp/odysseus-tmux/serve-gone.log; else "
        "tmux capture-pane -t serve-gone -p -S -600; fi"
    ]
