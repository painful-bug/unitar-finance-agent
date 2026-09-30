import pytest


@pytest.fixture(autouse=True)
def isolate_chat_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_CHAT_STORE_PATH", str(tmp_path / "default-chats"))
