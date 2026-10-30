"""DORA-style QA metrics from agent_runs and deploy_requests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from shared.models.domain import WorkflowType
from shared.persistence.database import get_session
from shared.persistence.models import AgentRunRecord, DeployRequestRecord


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


class QaMetricsRepository:
    async def aggregate_dora_metrics(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=days)
        async with get_session() as session:
            qa_runs_result = await session.execute(
                select(AgentRunRecord)
                .where(AgentRunRecord.workflow_type == WorkflowType.BRANCH_QA.value)
                .where(AgentRunRecord.created_at >= since)
                .order_by(AgentRunRecord.created_at.desc())
            )
            qa_runs = qa_runs_result.scalars().all()

            deploy_result = await session.execute(
                select(func.count(DeployRequestRecord.id))
                .where(DeployRequestRecord.created_at >= since)
                .where(DeployRequestRecord.status.in_(["published", "pipeline_ready", "waiting_pipeline"]))
            )
            deployments_30d = int(deploy_result.scalar() or 0)

        total = len(qa_runs)
        verdicts: dict[str, int] = {}
        lead_times: list[float] = []
        pass_count = 0
        fail_count = 0

        for run in qa_runs:
            out = run.output_payload or {}
            qa = out.get("qa") or {}
            verdict = str(qa.get("verdict") or "PENDING").upper()
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
            if verdict in ("PASS", "PASS_WITH_GAPS"):
                pass_count += 1
            elif verdict == "FAIL":
                fail_count += 1

            created = run.created_at
            updated = run.updated_at or run.created_at
            if created and updated:
                delta_min = (updated - created).total_seconds() / 60.0
                if delta_min >= 0:
                    lead_times.append(delta_min)

        change_failure_rate = round(fail_count / total * 100, 1) if total else 0.0
        pass_rate = round(pass_count / total * 100, 1) if total else 0.0
        avg_lead_time = round(sum(lead_times) / len(lead_times), 1) if lead_times else 0.0
        deployment_frequency = round(deployments_30d / max(days / 7, 1), 2)

        return {
            "period_days": days,
            "total_qa_runs": total,
            "pass_rate_pct": pass_rate,
            "change_failure_rate_pct": change_failure_rate,
            "avg_qa_lead_time_minutes": avg_lead_time,
            "deployments_30d": deployments_30d,
            "deployment_frequency_per_week": deployment_frequency,
            "verdict_breakdown": verdicts,
            "dora": {
                "deployment_frequency": {
                    "value": deployment_frequency,
                    "unit": "deployments/week",
                    "label": "Deployment Frequency",
                },
                "lead_time_for_changes": {
                    "value": avg_lead_time,
                    "unit": "minutes",
                    "label": "Lead Time (QA analysis)",
                },
                "change_failure_rate": {
                    "value": change_failure_rate,
                    "unit": "percent",
                    "label": "Change Failure Rate",
                },
                "mttr": {
                    "value": None,
                    "unit": "minutes",
                    "label": "MTTR (requires incident data)",
                    "note": "Connect Aegis incident slice for MTTR",
                },
            },
        }
