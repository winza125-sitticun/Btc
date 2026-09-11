"""Failure-isolated outbound alert adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import httpx


@dataclass(frozen=True)
class DeliveryResult:
    state: str
    error: str | None = None


class _Adapter:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def _post(self, url: str, *, json: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        async with httpx.AsyncClient(transport=self.transport, timeout=10.0) as client:
            response = await client.post(url, json=json, headers=headers)
            response.raise_for_status()


class TelegramAdapter(_Adapter):
    def __init__(self, *, bot_token: str, chat_id: str, transport=None) -> None:
        super().__init__(transport=transport); self.bot_token, self.chat_id = bot_token, chat_id

    async def send(self, message: str) -> None:
        await self._post(f"https://api.telegram.org/bot{self.bot_token}/sendMessage", json={"chat_id": self.chat_id, "text": message})


class LineAdapter(_Adapter):
    def __init__(self, *, channel_access_token: str, target_id: str, transport=None) -> None:
        super().__init__(transport=transport); self.channel_access_token, self.target_id = channel_access_token, target_id

    async def send(self, message: str) -> None:
        await self._post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {self.channel_access_token}"}, json={"to": self.target_id, "messages": [{"type": "text", "text": message}]})


class WebhookAdapter(_Adapter):
    def __init__(self, *, url: str, transport=None) -> None:
        super().__init__(transport=transport); self.url = url

    async def send(self, message: str) -> None:
        await self._post(self.url, json={"message": message})


async def deliver_alert(adapter: _Adapter, message: str) -> DeliveryResult:
    try:
        await adapter.send(message)
    except Exception as exc:
        return DeliveryResult("FAILED", type(exc).__name__)
    return DeliveryResult("DELIVERED")


async def persist_and_deliver_alert(repository, alert_id: int, adapter: _Adapter, message: str) -> DeliveryResult:
    """Deliver after persistence; delivery state errors never roll back the alert."""
    result = await deliver_alert(adapter, message)
    try:
        await repository.update_alert_delivery(alert_id=alert_id, delivery_state={"state": result.state, "error": result.error})
    except Exception:
        pass
    return result
