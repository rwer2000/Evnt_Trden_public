import httpx
import pytest

from congress_collector.notify import telegram


class _FakeResponse:
    def raise_for_status(self) -> None:
        pass


def test_send_message_posts_to_bot_api_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-5450631281")

    calls = []

    def fake_post(url: str, json: dict[str, str], timeout: float) -> _FakeResponse:
        calls.append((url, json, timeout))
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    telegram.send_message("nieuwe melding binnen", category="filing")

    assert len(calls) == 1
    url, payload, _timeout = calls[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert payload["chat_id"] == "-5450631281"
    assert payload["text"].endswith("nieuwe melding binnen")


def test_send_message_requires_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(KeyError):
        telegram.send_message("test")
