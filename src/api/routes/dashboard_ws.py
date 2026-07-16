import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.persistence.repository import AgentRunRepository, HITLRepository
from slices.knowledge.monitoring import KnowledgeMonitoringService

router = APIRouter(tags=["dashboard"])

_run_repo = AgentRunRepository()
_hitl_repo = HITLRepository()

_knowledge_connections: set[WebSocket] = set()
_connections: set[WebSocket] = set()


async def broadcast_knowledge_event(event: dict[str, Any]) -> None:
    dead: set[WebSocket] = set()
    for ws in _knowledge_connections:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    _knowledge_connections -= dead


@router.websocket("/ws/knowledge")
async def knowledge_dashboard_websocket(websocket: WebSocket):
    await websocket.accept()
    _knowledge_connections.add(websocket)
    monitoring = KnowledgeMonitoringService()
    try:
        while True:
            snapshot = await monitoring.get_monitoring_snapshot(runs_limit=25)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "knowledge_update",
                        "monitoring": snapshot.model_dump(mode="json"),
                    },
                    default=str,
                )
            )
            await asyncio.sleep(4)
    except WebSocketDisconnect:
        _knowledge_connections.discard(websocket)


async def broadcast_event(event: dict[str, Any]) -> None:
    dead: set[WebSocket] = set()
    for ws in _connections:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    _connections -= dead


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    await websocket.accept()
    _connections.add(websocket)
    try:
        while True:
            runs = await _run_repo.list_runs(limit=20)
            pending = await _hitl_repo.get_pending_checkpoints()
            stats = {
                "type": "dashboard_update",
                "runs": runs,
                "pending_hitl": [
                    {
                        "id": cp.id,
                        "run_id": cp.run_id,
                        "checkpoint_name": cp.checkpoint_name,
                        "description": cp.description,
                        "context": cp.context,
                    }
                    for cp in pending
                ],
            }
            await websocket.send_text(json.dumps(stats, default=str))
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        _connections.discard(websocket)
