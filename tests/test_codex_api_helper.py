from integrations.codex.scripts import odysseus_api
from integrations.codex.scripts.odysseus_api import _request_timeout


def test_scoped_chat_timeout_covers_sync_inference_window():
    assert _request_timeout("/api/codex/chat") == 130


def test_other_scoped_requests_keep_short_timeout():
    assert _request_timeout("/api/codex/capabilities") == 20


def test_chat_read_helper_builds_paginated_scoped_path(monkeypatch, capsys):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"{}"

    def urlopen(request, timeout):
        captured.update({
            "url": request.full_url,
            "method": request.method,
            "timeout": timeout,
        })
        return Response()

    monkeypatch.setattr(odysseus_api, "_config", lambda: ("http://odysseus", "token"))
    monkeypatch.setattr(odysseus_api.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(
        odysseus_api.sys,
        "argv",
        ["odysseus_api.py", "chat", "read", "session/id", "10", "25"],
    )

    assert odysseus_api.main() == 0
    assert capsys.readouterr().out.strip() == "{}"
    assert captured == {
        "url": "http://odysseus/api/codex/chat/session%2Fid?offset=10&limit=25",
        "method": "GET",
        "timeout": 20,
    }
