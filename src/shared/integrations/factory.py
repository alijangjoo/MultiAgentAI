from dataclasses import dataclass

from core.config import Settings, get_settings
from shared.integrations.confluence_client import MockConfluenceClient, RealConfluenceClient
from shared.integrations.elasticsearch_client import MockElasticsearchClient, RealElasticsearchClient
from shared.integrations.gitlab_client import MockGitLabClient, RealGitLabClient
from shared.integrations.jira_client import MockJiraClient, RealJiraClient
from shared.integrations.knowledge_service import MockKnowledgeService, RealKnowledgeService
from shared.integrations.local_knowledge_service import LocalRAGKnowledgeService
from shared.integrations.mattermost_client import MockMattermostClient, RealMattermostClient
from shared.integrations.protocols import (
    ConfluenceClientProtocol,
    ElasticsearchClientProtocol,
    GitLabClientProtocol,
    JiraClientProtocol,
    KnowledgeServiceProtocol,
    MattermostClientProtocol,
)


@dataclass
class IntegrationContainer:
    jira: JiraClientProtocol
    confluence: ConfluenceClientProtocol
    gitlab: GitLabClientProtocol
    mattermost: MattermostClientProtocol
    elasticsearch: ElasticsearchClientProtocol
    knowledge: KnowledgeServiceProtocol


def _build_jira(settings: Settings) -> JiraClientProtocol:
    if settings.should_mock_jira():
        return MockJiraClient()
    return RealJiraClient(
        url=settings.jira_url,
        username=settings.jira_username,
        api_token=settings.jira_api_token,
        verify_ssl=settings.jira_verify_ssl,
        auth_type=settings.jira_auth_type,  # type: ignore[arg-type]
        subtask_issue_type=settings.jira_subtask_issue_type,
        prd_field_id=settings.jira_prd_field_id,
    )


def _build_gitlab(settings: Settings) -> GitLabClientProtocol:
    if settings.should_mock_gitlab():
        return MockGitLabClient()
    project_id = settings.gitlab_project_id or None
    return RealGitLabClient(
        url=settings.gitlab_url,
        token=settings.gitlab_token,
        project_id=project_id,
        project_path=settings.gitlab_project_path,
        default_branch=settings.gitlab_default_branch,
        verify_ssl=settings.gitlab_verify_ssl,
    )


def _build_knowledge(settings: Settings) -> KnowledgeServiceProtocol:
    if settings.should_mock_knowledge():
        return MockKnowledgeService()
    if settings.use_local_knowledge or not settings.knowledge_service_url:
        return LocalRAGKnowledgeService()
    return RealKnowledgeService(
        url=settings.knowledge_service_url,
        api_key=settings.knowledge_service_api_key,
    )


def build_integrations(settings: Settings | None = None) -> IntegrationContainer:
    settings = settings or get_settings()

    if settings.use_mock_integrations and settings.should_mock_jira() and settings.should_mock_gitlab():
        return IntegrationContainer(
            jira=MockJiraClient(),
            confluence=MockConfluenceClient(),
            gitlab=MockGitLabClient(),
            mattermost=MockMattermostClient(),
            elasticsearch=MockElasticsearchClient(),
            knowledge=_build_knowledge(settings),
        )

    jira = _build_jira(settings)
    gitlab = _build_gitlab(settings)
    knowledge = _build_knowledge(settings)

    if settings.use_mock_integrations:
        return IntegrationContainer(
            jira=jira,
            confluence=MockConfluenceClient(),
            gitlab=gitlab,
            mattermost=MockMattermostClient(),
            elasticsearch=MockElasticsearchClient(),
            knowledge=knowledge,
        )

    return IntegrationContainer(
        jira=jira,
        confluence=RealConfluenceClient(
            url=settings.confluence_url,
            username=settings.confluence_username,
            api_token=settings.confluence_api_token,
        ),
        gitlab=gitlab,
        mattermost=RealMattermostClient(
            url=settings.mattermost_url,
            token=settings.mattermost_token,
        ),
        elasticsearch=RealElasticsearchClient(
            url=settings.elasticsearch_url,
            username=settings.elasticsearch_username,
            password=settings.elasticsearch_password,
            index_pattern=settings.elasticsearch_index_pattern,
        ),
        knowledge=knowledge,
    )
