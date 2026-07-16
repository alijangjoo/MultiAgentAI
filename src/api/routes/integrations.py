from fastapi import APIRouter, HTTPException

from api.schemas.requests import IntegrationHealthResponse, JiraIssueResponse
from shared.integrations.health import IntegrationHealthService

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])

_health = IntegrationHealthService()


@router.get("/health", response_model=IntegrationHealthResponse)
async def integration_health():
    """Test connectivity to Jira and GitLab using current .env settings."""
    result = await _health.check_all()
    return IntegrationHealthResponse(**result)


@router.get("/jira/health")
async def jira_health():
    return await _health.check_jira()


@router.get("/gitlab/health")
async def gitlab_health():
    return await _health.check_gitlab()


@router.get("/jira/issues/{issue_key}", response_model=JiraIssueResponse)
async def get_jira_issue(issue_key: str):
    """Fetch a Jira issue to verify read access before running agents."""
    try:
        issue = await _health.get_jira_issue(issue_key.upper())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Jira error: {exc}") from exc
    return JiraIssueResponse(**issue)


@router.get("/gitlab/project")
async def get_gitlab_project():
    """Return GitLab project metadata for the configured project."""
    try:
        project = await _health.get_gitlab_project()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc
    return project


@router.get("/gitlab/branches")
async def list_gitlab_branches(search: str | None = None, limit: int = 20):
    try:
        branches = await _health.list_gitlab_branches(search=search, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc
    return {"branches": branches, "count": len(branches)}
