"""Persistence for Deploy Request records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from shared.persistence.database import get_session
from shared.persistence.models import DeployRequestRecord
from slices.deploy_request.models.state import DeployRequest, DeployRequestStatus


def _to_domain(record: DeployRequestRecord) -> DeployRequest:
    return DeployRequest(
        id=record.id,
        run_id=record.run_id,
        hitl_checkpoint_id=record.hitl_checkpoint_id,
        status=DeployRequestStatus(record.status),
        mr_iid=record.mr_iid,
        mr_url=record.mr_url,
        source_branch=record.source_branch,
        target_branch=record.target_branch,
        pipeline_id=record.pipeline_id,
        pipeline_url=record.pipeline_url,
        version=record.version,
        jira_key=record.jira_key,
        jira_title=record.jira_title,
        jira_url=record.jira_url,
        app_name=record.app_name,
        service_name=record.service_name,
        endpoints=list(record.endpoints or []),
        changes_url=record.changes_url,
        priority=record.priority,
        publish_at=record.publish_at,
        message_body=record.message_body,
        mattermost_response=record.mattermost_response,
        error_message=record.error_message,
        created_at=record.created_at.isoformat() if record.created_at else None,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
    )


class DeployRequestRepository:
    async def create(self, req: DeployRequest) -> DeployRequest:
        if not req.id:
            req.id = str(uuid4())
        async with get_session() as session:
            session.add(
                DeployRequestRecord(
                    id=req.id,
                    run_id=req.run_id,
                    hitl_checkpoint_id=req.hitl_checkpoint_id,
                    status=req.status.value,
                    mr_iid=req.mr_iid,
                    mr_url=req.mr_url,
                    source_branch=req.source_branch,
                    target_branch=req.target_branch,
                    pipeline_id=req.pipeline_id,
                    pipeline_url=req.pipeline_url,
                    version=req.version,
                    jira_key=req.jira_key,
                    jira_title=req.jira_title,
                    jira_url=req.jira_url,
                    app_name=req.app_name,
                    service_name=req.service_name,
                    endpoints=req.endpoints,
                    changes_url=req.changes_url,
                    priority=req.priority,
                    publish_at=req.publish_at,
                    message_body=req.message_body,
                    mattermost_response=req.mattermost_response,
                    error_message=req.error_message,
                )
            )
        return req

    async def get(self, request_id: str) -> DeployRequest | None:
        async with get_session() as session:
            result = await session.execute(
                select(DeployRequestRecord).where(DeployRequestRecord.id == request_id)
            )
            record = result.scalar_one_or_none()
            return _to_domain(record) if record else None

    async def get_by_run_id(self, run_id: str) -> DeployRequest | None:
        async with get_session() as session:
            result = await session.execute(
                select(DeployRequestRecord)
                .where(DeployRequestRecord.run_id == run_id)
                .order_by(DeployRequestRecord.created_at.desc())
            )
            record = result.scalars().first()
            return _to_domain(record) if record else None

    async def get_by_mr_iid(self, mr_iid: int) -> DeployRequest | None:
        async with get_session() as session:
            result = await session.execute(
                select(DeployRequestRecord)
                .where(DeployRequestRecord.mr_iid == mr_iid)
                .order_by(DeployRequestRecord.created_at.desc())
            )
            record = result.scalars().first()
            return _to_domain(record) if record else None

    async def get_by_pipeline_id(self, pipeline_id: int) -> DeployRequest | None:
        async with get_session() as session:
            result = await session.execute(
                select(DeployRequestRecord)
                .where(DeployRequestRecord.pipeline_id == pipeline_id)
                .order_by(DeployRequestRecord.created_at.desc())
            )
            record = result.scalars().first()
            return _to_domain(record) if record else None

    async def find_waiting_for_pipeline(
        self,
        ref: str | None = None,
        pipeline_id: int | None = None,
    ) -> DeployRequest | None:
        async with get_session() as session:
            query = select(DeployRequestRecord).where(
                DeployRequestRecord.status.in_(
                    [
                        DeployRequestStatus.WAITING_PIPELINE.value,
                        DeployRequestStatus.PIPELINE_TRIGGERED.value,
                    ]
                )
            )
            if pipeline_id is not None:
                query = query.where(DeployRequestRecord.pipeline_id == pipeline_id)
            elif ref:
                query = query.where(DeployRequestRecord.target_branch == ref)
            query = query.order_by(DeployRequestRecord.created_at.desc())
            result = await session.execute(query)
            record = result.scalars().first()
            return _to_domain(record) if record else None

    async def list(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[DeployRequest]:
        async with get_session() as session:
            # Newest GitLab pipeline first (UI also re-sorts by pipeline_id)
            query = (
                select(DeployRequestRecord)
                .order_by(
                    DeployRequestRecord.pipeline_id.desc(),
                    DeployRequestRecord.created_at.desc(),
                )
                .limit(limit)
            )
            if status:
                query = query.where(DeployRequestRecord.status == status)
            result = await session.execute(query)
            return [_to_domain(r) for r in result.scalars().all()]

    async def update_fields(self, request_id: str, **fields: Any) -> DeployRequest | None:
        values: dict[str, Any] = {"updated_at": datetime.utcnow()}
        for key, value in fields.items():
            if value is None and key not in (
                "error_message",
                "hitl_checkpoint_id",
                "mattermost_response",
                "message_body",
                "publish_at",
                "priority",
                "version",
                "jira_key",
                "jira_title",
                "jira_url",
            ):
                continue
            if key == "status" and hasattr(value, "value"):
                values[key] = value.value
            elif key == "endpoints" and value is not None:
                values[key] = list(value)
            else:
                values[key] = value

        async with get_session() as session:
            await session.execute(
                update(DeployRequestRecord)
                .where(DeployRequestRecord.id == request_id)
                .values(**values)
            )
        return await self.get(request_id)
