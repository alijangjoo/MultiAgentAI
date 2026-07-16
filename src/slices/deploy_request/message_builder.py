"""Build Mattermost Deploy Request message text."""

from __future__ import annotations

from core.config import get_settings
from slices.deploy_request.models.state import DeployRequest


def build_deploy_message(req: DeployRequest) -> str:
    settings = get_settings()
    endpoints = ", ".join(req.endpoints) if req.endpoints else "dizi api"
    service = req.service_name or "Dizi service"
    app_name = req.app_name or "Dizi"

    # Feature/Page(s): Jira task browse URL (prefer), with optional title
    if req.jira_url:
        feature = req.jira_url
        if req.jira_title:
            feature = f"{req.jira_title} ({req.jira_url})"
    elif req.jira_key:
        base = (settings.jira_url or "https://desk.tapsifood.cloud").rstrip("/")
        browse = f"{base}/browse/{req.jira_key}"
        feature = f"{req.jira_title} ({browse})" if req.jira_title else browse
    else:
        feature = req.jira_title or "-"

    gitlab_link = req.mr_url or req.pipeline_url or "-"
    mention = settings.deploy_mention

    return (
        "Deploy Request\n"
        f"Service: [{app_name}] [{req.version or '-'}]\n"
        f"MR/GitLab Link: [{gitlab_link}]\n"
        f"Priority: [{req.priority or '-'}]\n"
        f"Date&Times: [{req.publish_at or '-'}]\n"
        f"Changes: [{req.changes_url or '-'}]\n"
        "Impacted Areas (What changed?):\n"
        f" API(s): [{endpoints}]\n"
        f"Service(s): [{service}]\n"
        f"Feature/Page(s): [{feature}]\n"
        "Database/Cache: -\n"
        "Database renamed: NO\n"
        "Dev Test Coverage: -\n"
        "Risks / Side Effects: -\n"
        "Developer Approval: Approved\n"
        f"{mention}"
    )
