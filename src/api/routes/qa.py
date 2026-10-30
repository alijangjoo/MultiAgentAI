"""API routes for Branch QA Agent."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from shared.qa.git_diff import GitDiffError

from api.services.qa_service import QaService
from slices.qa.template_loader import (
    apply_qa_template_placeholders,
    load_acceptance_criteria_template,
    load_feature_brief_template,
)

router = APIRouter(prefix="/api/v1/qa", tags=["qa"])


class QaBranchRequest(BaseModel):
    branch_name: str = Field(..., min_length=1, description="Feature branch to QA")
    target_branch: str | None = Field(default=None, description="Base branch (default: dev target from settings)")
    repo_path: str | None = Field(
        default=None,
        description="Local git clone path (overrides CURSOR_REPO_PATH from .env)",
    )
    acceptance_criteria: str | None = None
    feature_brief: str | None = None
    title: str | None = None
    language: str = Field(default="fa", description="Output language: fa or en")


class QaTemplatesResponse(BaseModel):
    acceptance_criteria_template: str
    feature_brief_template: str
    branch_name: str = ""
    target_branch: str = ""
    jira_key: str = "TBD"


class QaRunSummary(BaseModel):
    id: str
    status: str
    branch_name: str | None = None
    target_branch: str | None = None
    task_key: str | None = None
    verdict: str | None = None
    test_case_count: int = 0
    created_at: str
    error_message: str | None = None


@router.get("/templates", response_model=QaTemplatesResponse)
async def get_qa_templates(
    branch_name: str = "",
    target_branch: str = "",
    jira_key: str = "TBD",
):
    ac = load_acceptance_criteria_template()
    brief = load_feature_brief_template()
    return QaTemplatesResponse(
        acceptance_criteria_template=apply_qa_template_placeholders(
            ac,
            branch_name=branch_name,
            target_branch=target_branch,
            jira_key=jira_key,
        ),
        feature_brief_template=apply_qa_template_placeholders(
            brief,
            branch_name=branch_name,
            target_branch=target_branch,
            jira_key=jira_key,
        ),
        branch_name=branch_name,
        target_branch=target_branch,
        jira_key=jira_key,
    )


@router.get("/branches")
async def list_qa_branches(
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    service = QaService()
    branches = await service.list_branches(search=search, limit=limit)
    return {"branches": branches, "count": len(branches)}


@router.post("/analyze")
async def analyze_branch(request: QaBranchRequest):
    service = QaService()
    try:
        result = await service.run_branch_qa(
            branch_name=request.branch_name.strip(),
            target_branch=request.target_branch,
            repo_path=request.repo_path,
            acceptance_criteria=request.acceptance_criteria,
            feature_brief=request.feature_brief,
            title=request.title,
            language=request.language,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitDiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        msg = str(exc)
        if "git" in msg.lower():
            raise HTTPException(status_code=400, detail=msg) from exc
        raise HTTPException(status_code=500, detail=msg) from exc


@router.get("/runs", response_model=list[QaRunSummary])
async def list_qa_runs(limit: int = Query(default=50, ge=1, le=200)):
    service = QaService()
    runs = await service.list_runs(limit=limit)
    summaries: list[QaRunSummary] = []
    for run in runs:
        inp = run.get("input_payload") or {}
        out = run.get("output_payload") or {}
        qa = out.get("qa") or {}
        summaries.append(
            QaRunSummary(
                id=run["id"],
                status=run["status"],
                branch_name=inp.get("branch_name") or out.get("branch_name"),
                target_branch=inp.get("target_branch") or out.get("target_branch"),
                task_key=inp.get("task_key") or out.get("task_key"),
                verdict=qa.get("verdict"),
                test_case_count=len(qa.get("test_cases") or []),
                created_at=run["created_at"],
                error_message=run.get("error_message"),
            )
        )
    return summaries


@router.get("/runs/{run_id}")
async def get_qa_run(run_id: str):
    service = QaService()
    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="QA run not found")
    return run


class QaExportRequest(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["pytest", "cypress", "markdown"])
    commit_to_branch: bool | None = None


class QaJiraAttachRequest(BaseModel):
    issue_key: str | None = None


@router.get("/metrics")
async def qa_dora_metrics(days: int = Query(default=30, ge=1, le=365)):
    service = QaService()
    return await service.get_dora_metrics(days=days)


@router.get("/gate")
async def qa_quality_gate(branch: str = Query(..., min_length=1)):
    """Quality gate for release pipeline — GitLab CI can curl this endpoint."""
    service = QaService()
    result = await service.check_branch_gate(branch.strip())
    if not result.get("passed"):
        raise HTTPException(status_code=403, detail=result)
    return result


@router.post("/runs/{run_id}/export")
async def export_qa_tests(run_id: str, request: QaExportRequest | None = None):
    service = QaService()
    req = request or QaExportRequest()
    try:
        return await service.export_test_files(
            run_id,
            formats=req.formats,
            commit_to_branch=req.commit_to_branch,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/attach-jira")
async def attach_qa_to_jira(run_id: str, request: QaJiraAttachRequest | None = None):
    service = QaService()
    req = request or QaJiraAttachRequest()
    try:
        return await service.attach_to_jira(run_id, issue_key=req.issue_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
