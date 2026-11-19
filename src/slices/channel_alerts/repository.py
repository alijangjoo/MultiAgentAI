"""Persistence for Disaster / Bugs channel messages."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from shared.persistence.database import get_session
from shared.persistence.models import ChannelAlertRecord
from slices.channel_alerts.models import ChannelAlert, Classification, IncomingAlert


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def to_domain(record: ChannelAlertRecord) -> ChannelAlert:
    return ChannelAlert(
        id=record.id,
        external_id=record.external_id,
        list_name=record.list_name,
        channel_id=record.channel_id or "",
        channel_name=record.channel_name or "",
        user_name=record.user_name or "",
        text=record.text,
        vendor_related=bool(record.vendor_related),
        vendor_name=record.vendor_name or "",
        vendor_reason=record.vendor_reason or "",
        confidence=float(record.confidence or 0),
        classifier=record.classifier or "",
        classification_status=record.classification_status or "pending",
        knowledge_hits=list(record.knowledge_hits or []),
        created_at=_iso(record.created_at),
    )


class ChannelAlertRepository:
    async def get(self, alert_id: str) -> ChannelAlert | None:
        async with get_session() as session:
            record = await session.get(ChannelAlertRecord, alert_id)
            return to_domain(record) if record else None

    async def save_pending(self, incoming: IncomingAlert) -> ChannelAlert:
        async with get_session() as session:
            existing = await session.scalar(
                select(ChannelAlertRecord).where(ChannelAlertRecord.external_id == incoming.external_id)
            )
            if existing is not None:
                if existing.text == incoming.text and existing.classification_status == "done":
                    return to_domain(existing)
                existing.text = incoming.text
                existing.list_name = incoming.list_name
                existing.channel_id = incoming.channel_id
                existing.channel_name = incoming.channel_name
                existing.user_name = incoming.user_name
                existing.classification_status = "pending"
                existing.vendor_related = False
                existing.vendor_name = ""
                existing.vendor_reason = ""
                existing.confidence = 0
                return to_domain(existing)

            record = ChannelAlertRecord(
                id=str(uuid4()),
                external_id=incoming.external_id,
                list_name=incoming.list_name,
                channel_id=incoming.channel_id,
                channel_name=incoming.channel_name,
                user_name=incoming.user_name,
                text=incoming.text,
                classification_status="pending",
                knowledge_hits=[],
            )
            session.add(record)
            await session.flush()
            return to_domain(record)

    async def mark_pending(self, alert_id: str) -> ChannelAlert | None:
        async with get_session() as session:
            record = await session.get(ChannelAlertRecord, alert_id)
            if record is None:
                return None
            record.classification_status = "pending"
            record.vendor_reason = "در حال بررسی"
            return to_domain(record)

    async def list_open_ids(self, limit: int = 100) -> list[str]:
        stmt = (
            select(ChannelAlertRecord.id)
            .where(ChannelAlertRecord.vendor_related.is_(False))
            .order_by(ChannelAlertRecord.created_at.desc())
            .limit(limit)
        )
        async with get_session() as session:
            return list((await session.scalars(stmt)).all())

    async def apply_classification(self, alert_id: str, result: Classification) -> ChannelAlert | None:
        async with get_session() as session:
            record = await session.get(ChannelAlertRecord, alert_id)
            if record is None:
                return None
            record.vendor_related = bool(result.vendor_related) and result.status == "done"
            record.vendor_name = result.vendor_name if record.vendor_related else ""
            record.vendor_reason = result.reason
            record.confidence = result.confidence
            record.classifier = result.classifier
            record.classification_status = result.status
            record.knowledge_hits = list(result.knowledge_hits)
            return to_domain(record)

    async def list_alerts(self, kind: str, limit: int = 100) -> list[ChannelAlert]:
        stmt = select(ChannelAlertRecord)
        if kind == "vendor":
            stmt = stmt.where(ChannelAlertRecord.vendor_related.is_(True))
        elif kind in {"disaster", "bugs"}:
            stmt = stmt.where(ChannelAlertRecord.list_name == kind)
        else:
            raise ValueError("kind must be disaster, bugs, or vendor")
        stmt = stmt.order_by(ChannelAlertRecord.created_at.desc()).limit(limit)
        async with get_session() as session:
            records = (await session.scalars(stmt)).all()
            return [to_domain(record) for record in records]