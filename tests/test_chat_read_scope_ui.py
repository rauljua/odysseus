from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_integration_permissions_expose_chat_history_read():
    source = (ROOT / "static/js/settings.js").read_text(encoding="utf-8")

    assert "key: 'chat:read', label: 'Chat history'" in source
    assert "chat: '<svg" in source


def test_admin_permissions_expose_history_and_preserve_base_chat_scope():
    source = (ROOT / "static/js/admin.js").read_text(encoding="utf-8")

    assert "key: 'chat:read',         label: 'Chat history read'" in source
    assert "const scopes = ['chat'].concat(" in source
