from shared.integrations.factory import IntegrationContainer
from shared.integrations.registry import get_integrations
from shared.models.domain import AgentName, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository
from slices.incident_response.agents.aegis import run_aegis
from slices.incident_response.models.state import AegisOutput, IncidentAnalysisInput


class IncidentResponseOrchestrator:
    def __init__(
        self,
        integrations: IntegrationContainer | None = None,
        run_repo: AgentRunRepository | None = None,
    ):
        self._integrations = integrations or get_integrations()
        self._run_repo = run_repo or AgentRunRepository()

    async def analyze_disaster_channel(
        self,
        input_data: IncidentAnalysisInput,
    ) -> tuple[str, AegisOutput]:
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.INCIDENT_RESPONSE.value,
            agent_name=AgentName.AEGIS,
            input_payload=input_data.model_dump(),
        )

        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.AEGIS,
            "incident_analysis_started",
            "Starting Disaster channel incident analysis",
        )

        try:
            output = await run_aegis(
                run_id=run_id,
                channel_id=input_data.channel_id,
                integrations=self._integrations,
                repo=self._run_repo,
            )

            await self._run_repo.update_run(
                run_id,
                status=RunStatus.COMPLETED,
                output_payload=output.model_dump(mode="json"),
            )

            await self._run_repo.log_event_by_type(
                run_id,
                AgentName.AEGIS,
                "incident_analysis_completed",
                f"Report ready for Tech Lead: {output.report.title}",
                {"severity": output.report.severity},
            )

            return run_id, output

        except Exception as exc:
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise
