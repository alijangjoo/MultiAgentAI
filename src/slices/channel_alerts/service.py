"""Accept channel webhooks and classify vendor-related messages."""

from __future__ import annotations

from typing import Any

from slices.channel_alerts.classifier import classify_message
from slices.channel_alerts.models import ChannelAlert, Classification
from slices.channel_alerts.payload import normalize_payload
from slices.channel_alerts.repository import ChannelAlertRepository


class ChannelAlertService:
    def __init__(self, repo: ChannelAlertRepository | None = None, classifier=None):
        self._repo = repo or ChannelAlertRepository()
        self._classifier = classifier or classify_message

    async def accept(self, payload: dict[str, Any]) -> ChannelAlert:
        incoming = normalize_payload(payload)
        return await self._repo.save_pending(incoming)

    async def classify_saved(self, alert_id: str) -> ChannelAlert | None:
        current = await self._repo.get(alert_id)
        if current is None:
            return None
        if current.classification_status == "done":
            return current
        result = await self._classifier(current.text)
        return await self._repo.apply_classification(alert_id, result)

    async def prepare_recheck(self, alert_id: str) -> ChannelAlert | None:
        return await self._repo.mark_pending(alert_id)

    async def open_ids(self, limit: int = 100) -> list[str]:
        return await self._repo.list_open_ids(limit=limit)

    async def manual_review(
        self,
        alert_id: str,
        *,
        vendor_related: bool,
        vendor_name: str = "",
        reason: str = "",
    ) -> ChannelAlert | None:
        note = (reason or "").strip() or (
            "بررسی دستی: وندور" if vendor_related else "بررسی دستی: وندور نیست"
        )
        result = Classification(
            vendor_related=vendor_related,
            vendor_name=vendor_name.strip() if vendor_related else "",
            reason=note,
            confidence=1.0 if vendor_related else 0.0,
            classifier="manual",
            knowledge_hits=[],
            status="done",
        )
        return await self._repo.apply_classification(alert_id, result)

    async def list_alerts(self, kind: str, limit: int = 100) -> list[ChannelAlert]:
        return await self._repo.list_alerts(kind, limit=limit)