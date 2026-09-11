import asyncio

import httpx

from btc_core.strategy.alert_delivery import LineAdapter, TelegramAdapter, WebhookAdapter, deliver_alert


def test_telegram_secret_is_only_in_url_and_not_payload():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    adapter = TelegramAdapter(bot_token="secret-token", chat_id="chat-1", transport=httpx.MockTransport(handler))
    asyncio.run(adapter.send("hello"))
    assert "secret-token" in str(requests[0].url)
    assert "secret-token" not in requests[0].content.decode()


def test_line_secret_is_outbound_header_only():
    requests = []
    adapter = LineAdapter(channel_access_token="line-secret", target_id="target", transport=httpx.MockTransport(lambda r: (requests.append(r) or httpx.Response(200))))
    asyncio.run(adapter.send("hello"))
    assert requests[0].headers["Authorization"] == "Bearer line-secret"
    assert "line-secret" not in requests[0].content.decode()


def test_webhook_failure_is_isolated_and_returns_delivery_state():
    adapter = WebhookAdapter(url="https://example.test/hook", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    result = asyncio.run(deliver_alert(adapter, "hello"))
    assert result.state == "FAILED"
    assert result.error
