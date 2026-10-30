"""Orchestrate branch QA workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.config import get_settings
from shared.agent_executors.qa_executor import execute_qa
from shared.models.domain import AgentName, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository
from shared.qa.exporters import (
    export_cypress_spec,
    export_pytest_module,
    export_test_cases_markdown,
    write_export_files,
)
from shared.qa.git_diff import GitDiffError, fetch_branch_diff, format_diff_for_prompt
from shared.qa.metrics_repository import QaMetricsRepository
from shared.qa.models import QaContext, QaResult
from shared.qa.quality_gate import check_qa_gate
from shared.utils.jira_key_from_branch import extract_jira_key_from_branch
from slices.qa.template_loader import is_template_placeholder


def resolve_qa_repo_path(explicit: str | None = None) -> str:
    settings = get_settings()
    for candidate in (explicit, settings.cursor_repo_path):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    raise ValueError(
        "Local repo path is not set. Enter it in the QA dashboard or set CURSOR_REPO_PATH in .env"
    )


class QaService:
    def __init__(self, repo: AgentRunRepository | None = None) -> None:
        self._repo = repo or AgentRunRepository()

    async def list_branches(self, *, search: str | None = None, limit: int = 100) -> list[str]:
        from shared.integrations.registry import get_integrations
        from shared.utils.gitlab_branches import normalize_branch_list

        settings = get_settings()
        integrations = get_integrations()
        gitlab = integrations.gitlab
        remote: list[str] = []
        if hasattr(gitlab, "list_branches"):
            remote = await gitlab.list_branches(search=search, limit=limit)
        return normalize_branch_list(remote, limit=limit)

    async def run_branch_qa(
        self,
        *,
        branch_name: str,
        target_branch: str | None = None,
        acceptance_criteria: str | None = None,
        feature_brief: str | None = None,
        title: str | None = None,
        language: str = "fa",
        repo_path: str | None = None,
    ) -> dict:
        settings = get_settings()
        target = target_branch or settings.gitlab_mr_target_dev or settings.gitlab_feature_source_branch
        task_key = extract_jira_key_from_branch(branch_name)
        resolved_repo = resolve_qa_repo_path(repo_path)

        run_id = await self._repo.create_run(
            WorkflowType.BRANCH_QA.value,
            AgentName.QA,
            {
                "branch_name": branch_name,
                "target_branch": target,
                "task_key": task_key,
                "title": title,
                "repo_path": resolved_repo,
            },
        )
        await self._repo.update_run(run_id, status=RunStatus.RUNNING)

        try:
            diff_text, changed_files = await asyncio.to_thread(
                fetch_branch_diff,
                resolved_repo,
                branch_name,
                target,
            )
            formatted_diff = format_diff_for_prompt(diff_text, changed_files)

            ac_placeholder = is_template_placeholder(acceptance_criteria)
            brief_placeholder = is_template_placeholder(feature_brief)

            context = QaContext(
                branch_name=branch_name,
                target_branch=target,
                task_key=task_key,
                title=title,
                git_diff=formatted_diff,
                acceptance_criteria=acceptance_criteria,
                feature_brief=feature_brief,
                language=language,
                extra_context={
                    "changed_file_count": str(len(changed_files)),
                    "inputs_status": (
                        "acceptance_criteria_placeholder"
                        if ac_placeholder
                        else "acceptance_criteria_provided"
                    )
                    + ";"
                    + (
                        "feature_brief_placeholder"
                        if brief_placeholder
                        else "feature_brief_provided"
                    ),
                },
            )

            await self._repo.log_event_by_type(
                run_id,
                AgentName.QA,
                "diff_loaded",
                f"Loaded diff: {len(changed_files)} files, {len(diff_text)} chars",
                {"changed_files": changed_files[:50]},
            )

            exec_result = await execute_qa(
                run_id=run_id,
                context=context,
                repo=self._repo,
                repo_path=resolved_repo,
            )
            qa_result = exec_result["result"]

            if ac_placeholder or brief_placeholder:
                missing = list(qa_result.get("missing_inputs") or [])
                if ac_placeholder and "Acceptance Criteria template" not in " ".join(missing):
                    missing.append("Acceptance Criteria template — fill docs/templates/qa/ACCEPTANCE_CRITERIA_TEMPLATE.md")
                if brief_placeholder and "Feature Brief template" not in " ".join(missing):
                    missing.append("Feature Brief template — fill docs/templates/qa/FEATURE_BRIEF_TEMPLATE.md")
                qa_result["missing_inputs"] = missing
                if qa_result.get("verdict") == "PASS":
                    qa_result["verdict"] = "NEEDS_INPUT"
                    qa_result["ready"] = False

            output = {
                "branch_name": branch_name,
                "target_branch": target,
                "task_key": task_key,
                "changed_files": changed_files,
                "qa": qa_result,
                "executor": exec_result.get("executor"),
                "backend": exec_result.get("backend"),
                "prompt_preview": (exec_result.get("prompt") or "")[:4000],
                "cli_stdout": exec_result.get("cli_stdout", ""),
            }

            await self._repo.update_run(
                run_id,
                status=RunStatus.COMPLETED,
                output_payload=output,
            )
            return {"run_id": run_id, "status": RunStatus.COMPLETED.value, **output}

        except GitDiffError as exc:
            await self._repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            await self._repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def get_run(self, run_id: str) -> dict | None:
        return await self._repo.get_run(run_id)

    async def list_runs(self, limit: int = 50) -> list[dict]:
        return await self._repo.list_runs(
            workflow_type=WorkflowType.BRANCH_QA.value,
            agent_name=AgentName.QA,
            limit=limit,
        )

    async def get_latest_qa_for_branch(self, branch_name: str) -> dict | None:
        runs = await self.list_runs(limit=200)
        for run in runs:
            if run.get("status") != RunStatus.COMPLETED.value:
                continue
            inp = run.get("input_payload") or {}
            out = run.get("output_payload") or {}
            if inp.get("branch_name") == branch_name or out.get("branch_name") == branch_name:
                return run
        return None

    async def check_branch_gate(self, branch_name: str) -> dict:
        run = await self.get_latest_qa_for_branch(branch_name)
        if not run:
            gate = check_qa_gate(None)
            return {
                **gate,
                "passed": False if get_settings().qa_gate_enabled else True,
                "branch_name": branch_name,
                "run_id": None,
                "message": "No completed QA run found for this branch",
            }
        out = run.get("output_payload") or {}
        qa = out.get("qa") or {}
        gate = check_qa_gate(qa.get("verdict"), ready=qa.get("ready"))
        return {
            **gate,
            "branch_name": branch_name,
            "run_id": run["id"],
            "task_key": out.get("task_key"),
            "test_case_count": len(qa.get("test_cases") or []),
        }

    async def get_dora_metrics(self, *, days: int = 30) -> dict:
        repo = QaMetricsRepository()
        return await repo.aggregate_dora_metrics(days=days)

    def _qa_result_from_run(self, run: dict) -> tuple[QaResult, dict]:
        out = run.get("output_payload") or {}
        qa_data = out.get("qa") or {}
        return QaResult(**qa_data), out

    async def export_test_files(
        self,
        run_id: str,
        *,
        formats: list[str] | None = None,
        commit_to_branch: bool | None = None,
    ) -> dict:
        run = await self.get_run(run_id)
        if not run:
            raise ValueError("QA run not found")
        qa, out = self._qa_result_from_run(run)
        branch = out.get("branch_name") or (run.get("input_payload") or {}).get("branch_name") or ""
        task_key = out.get("task_key")
        settings = get_settings()
        wanted = {f.lower() for f in (formats or ["pytest", "cypress", "markdown"])}

        files: dict[str, str] = {}
        if "pytest" in wanted:
            path, content = export_pytest_module(qa, task_key=task_key, branch_name=branch)
            files[path] = content
        if "cypress" in wanted:
            path, content = export_cypress_spec(qa, task_key=task_key, branch_name=branch)
            files[path] = content
        if "markdown" in wanted:
            md = export_test_cases_markdown(qa, task_key=task_key, branch_name=branch, run_id=run_id)
            key = (task_key or "qa").lower()
            files[f"docs/qa/{key}_test_cases.md"] = md

        root = Path(__file__).resolve().parents[3]
        export_base = root / settings.qa_export_dir
        written = write_export_files(export_base, run_id, files)

        result: dict = {"run_id": run_id, "files": written, "formats": sorted(wanted)}
        do_commit = settings.qa_export_commit_to_branch if commit_to_branch is None else commit_to_branch
        if do_commit and branch and files:
            from shared.integrations.registry import get_integrations

            gitlab = get_integrations().gitlab
            if hasattr(gitlab, "commit_files"):
                msg = f"test({task_key or 'qa'}): QA Agent export pytest/cypress"
                commit_result = await gitlab.commit_files(branch, msg, files)
                result["git_commit"] = commit_result

        await self._repo.log_event_by_type(
            run_id,
            AgentName.QA,
            "tests_exported",
            f"Exported {len(written)} file(s)",
            {"files": [w["relative"] for w in written]},
        )
        return result

    async def attach_to_jira(self, run_id: str, *, issue_key: str | None = None) -> dict:
        run = await self.get_run(run_id)
        if not run:
            raise ValueError("QA run not found")
        qa, out = self._qa_result_from_run(run)
        branch = out.get("branch_name") or ""
        task_key = (issue_key or out.get("task_key") or "").upper()
        if not task_key:
            raise ValueError("No Jira issue key — provide issue_key or use a branch with Jira key")

        settings = get_settings()
        root = Path(__file__).resolve().parents[3]
        export_base = root / settings.qa_export_dir / run_id
        export_base.mkdir(parents=True, exist_ok=True)

        md = export_test_cases_markdown(qa, task_key=task_key, branch_name=branch, run_id=run_id)
        md_path = export_base / f"{task_key}_qa_test_cases.md"
        md_path.write_text(md, encoding="utf-8")

        from shared.integrations.registry import get_integrations

        jira = get_integrations().jira
        comment_body = (
            f"h3. QA Agent Report — {task_key}\n"
            f"*Branch:* {branch}\n"
            f"*Verdict:* {qa.verdict}\n"
            f"*Test Cases:* {len(qa.test_cases)}\n"
            f"*Summary:* {qa.summary[:500] if qa.summary else '—'}\n"
            f"*Run ID:* {run_id}"
        )
        comment = await jira.add_comment(task_key, comment_body)
        attachment = await jira.add_attachment(task_key, str(md_path), filename=f"{task_key}_qa_test_cases.md")

        await self._repo.log_event_by_type(
            run_id,
            AgentName.QA,
            "jira_attached",
            f"Attached QA report to {task_key}",
            {"issue_key": task_key, "filename": md_path.name},
        )
        return {
            "run_id": run_id,
            "issue_key": task_key,
            "comment": comment,
            "attachment": attachment,
            "markdown_path": str(md_path),
        }
