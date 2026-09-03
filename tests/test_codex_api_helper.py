from integrations.codex.scripts.odysseus_api import _request_timeout


def test_scoped_chat_timeout_covers_sync_inference_window():
    assert _request_timeout("/api/codex/chat") == 130


def test_other_scoped_requests_keep_short_timeout():
    assert _request_timeout("/api/codex/capabilities") == 20
