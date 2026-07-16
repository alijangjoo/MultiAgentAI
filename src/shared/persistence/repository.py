from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from shared.models.domain import (
    AgentName,
    AgentRunEvent,
    HITLAction,
    HITLCheckpoint,
    RunStatus,
)
from shared.persistence.database import get_session
from shared.persistence.models import AgentEventRecord, AgentRunRecord, HITLCheckpointRecord


class AgentRunRepository:
    async def create_run(
        self,
        workflow_type: str,
        agent_name: AgentName,
        input_payload: dict[str, Any],
        parent_run_id: str | None = None,
    ) -> str:
        run_id = str(uuid4())
        async with get_session() as session:
            record = AgentRunRecord(
                id=run_id,
                workflow_type=workflow_type,
                agent_name=agent_name.value,
                status=RunStatus.PENDING.value,
                input_payload=input_payload,
                output_payload={},
                parent_run_id=parent_run_id,
            )
            session.add(record)
        return run_id

    async def update_run(
        self,
        run_id: str,
        status: RunStatus | None = None,
        output_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"updated_at": datetime.utcnow()}
        if status:
            values["status"] = status.value
        if output_payload is not None:
            values["output_payload"] = output_payload
        if error_message is not None:
            values["error_message"] = error_message

        async with get_session() as session:
            await session.execute(
                update(AgentRunRecord).where(AgentRunRecord.id == run_id).values(**values)
            )

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        async with get_session() as session:
            result = await session.execute(
                select(AgentRunRecord).where(AgentRunRecord.id == run_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None
            return {
                "id": record.id,
                "workflow_type": record.workflow_type,
                "agent_name": record.agent_name,
                "status": record.status,
                "input_payload": record.input_payload,
                "output_payload": record.output_payload,
                "error_message": record.error_message,
                "parent_run_id": record.parent_run_id,
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
            }

    async def list_runs(
        self,
        workflow_type: str | None = None,
        status: RunStatus | None = None,
        agent_name: AgentName | str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with get_session() as session:
            query = select(AgentRunRecord).order_by(AgentRunRecord.created_at.desc()).limit(limit)
            if workflow_type:
                query = query.where(AgentRunRecord.workflow_type == workflow_type)
            if status:
                query = query.where(AgentRunRecord.status == status.value)
            if agent_name:
                name = agent_name.value if isinstance(agent_name, AgentName) else agent_name
                query = query.where(AgentRunRecord.agent_name == name)
            result = await session.execute(query)
            records = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "workflow_type": r.workflow_type,
                    "agent_name": r.agent_name,
                    "status": r.status,
                    "input_payload": r.input_payload,
                    "output_payload": r.output_payload,
                    "error_message": r.error_message,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in records
            ]

    async def list_events_by_agent(
        self,
        agent_name: AgentName,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        async with get_session() as session:
            result = await session.execute(
                select(AgentEventRecord)
                .where(AgentEventRecord.agent_name == agent_name.value)
                .order_by(AgentEventRecord.created_at.desc())
                .limit(limit)
            )
            records = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "run_id": r.run_id,
                    "agent_name": r.agent_name,
                    "event_type": r.event_type,
                    "message": r.message,
                    "payload": r.payload,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ]

    async def log_event(self, event: AgentRunEvent) -> None:
        async with get_session() as session:
            session.add(
                AgentEventRecord(
                    id=event.id,
                    run_id=event.run_id,
                    agent_name=event.agent_name.value,
                    event_type=event.event_type,
                    message=event.message,
                    payload=event.payload,
                    created_at=event.created_at,
                )
            )

    async def log_event_by_type(
        self,
        run_id: str,
        agent_name: AgentName,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self.log_event(
            AgentRunEvent(
                run_id=run_id,
                agent_name=agent_name,
                event_type=event_type,
                message=message,
                payload=payload or {},
            )
        )

    async def get_events(self, run_id: str) -> list[dict[str, Any]]:
        async with get_session() as session:
            result = await session.execute(
                select(AgentEventRecord)
                .where(AgentEventRecord.run_id == run_id)
                .order_by(AgentEventRecord.created_at)
            )
            records = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "run_id": r.run_id,
                    "agent_name": r.agent_name,
                    "event_type": r.event_type,
                    "message": r.message,
                    "payload": r.payload,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ]


class HITLRepository:
    async def create_checkpoint(self, checkpoint: HITLCheckpoint) -> HITLCheckpoint:
        async with get_session() as session:
            session.add(
                HITLCheckpointRecord(
                    id=checkpoint.id,
                    run_id=checkpoint.run_id,
                    checkpoint_name=checkpoint.checkpoint_name,
                    description=checkpoint.description,
                    context=checkpoint.context,
                    resolved=checkpoint.resolved,
                    created_at=checkpoint.created_at,
                )
            )
        return checkpoint

    async def resolve_checkpoint(
        self,
        checkpoint_id: str,
        action: HITLAction,
        resolved_by: str,
    ) -> HITLCheckpoint | None:
        async with get_session() as session:
            result = await session.execute(
                select(HITLCheckpointRecord).where(HITLCheckpointRecord.id == checkpoint_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None

            record.resolved = True
            record.action = action.value
            record.resolved_by = resolved_by
            record.resolved_at = datetime.utcnow()

            return HITLCheckpoint(
                id=record.id,
                run_id=record.run_id,
                checkpoint_name=record.checkpoint_name,
                description=record.description,
                context=record.context,
                resolved=record.resolved,
                action=action,
                resolved_by=record.resolved_by,
                resolved_at=record.resolved_at,
                created_at=record.created_at,
            )

    async def get_pending_checkpoints(self, run_id: str | None = None) -> list[HITLCheckpoint]:
        async with get_session() as session:
            query = select(HITLCheckpointRecord).where(HITLCheckpointRecord.resolved.is_(False))
            if run_id:
                query = query.where(HITLCheckpointRecord.run_id == run_id)
            query = query.order_by(HITLCheckpointRecord.created_at.desc())
            result = await session.execute(query)
            records = result.scalars().all()
            return [
                HITLCheckpoint(
                    id=r.id,
                    run_id=r.run_id,
                    checkpoint_name=r.checkpoint_name,
                    description=r.description,
                    context=r.context,
                    resolved=r.resolved,
                    action=HITLAction(r.action) if r.action else None,
                    resolved_by=r.resolved_by,
                    resolved_at=r.resolved_at,
                    created_at=r.created_at,
                )
                for r in records
            ]

    async def get_checkpoint(self, checkpoint_id: str) -> HITLCheckpoint | None:
        async with get_session() as session:
            result = await session.execute(
                select(HITLCheckpointRecord).where(HITLCheckpointRecord.id == checkpoint_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None
            return HITLCheckpoint(
                id=record.id,
                run_id=record.run_id,
                checkpoint_name=record.checkpoint_name,
                description=record.description,
                context=record.context,
                resolved=record.resolved,
                action=HITLAction(record.action) if record.action else None,
                resolved_by=record.resolved_by,
                resolved_at=record.resolved_at,
                created_at=record.created_at,
            )
