from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AgentFramework"
    app_env: str = "development"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_provider: str = "openai"
    anthropic_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    coding_model: str = "gpt-4o-mini"
    code_review_model: str = "gpt-4o"
    pm_model: str = "gpt-4o"
    prd_template_path: str = "docs/templates/PRD_TEMPLATE.md"

    forge_executor: str = "cursor"
    sentinel_executor: str = "cursor"
    cursor_api_key: str = ""
    cursor_repo_path: str = ""
    cursor_bridge_url: str = "http://127.0.0.1:9090"
    cursor_model: str = "composer-2.5"

    jira_url: str = ""
    jira_username: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "VEN"
    jira_verify_ssl: bool = True
    jira_auth_type: str = "pat"
    jira_subtask_issue_type: str | None = None
    jira_prd_field_id: str | None = None
    use_mock_jira: bool | None = None

    confluence_url: str = ""
    confluence_username: str = ""
    confluence_api_token: str = ""
    confluence_space_key: str = "ENG"

    gitlab_url: str = ""
    gitlab_token: str = ""
    gitlab_project_id: int | None = None
    gitlab_project_path: str | None = None
    gitlab_default_branch: str = "develop"
    gitlab_feature_source_branch: str = "main"
    gitlab_mr_target_dev: str = "dev-oms-v2"
    gitlab_mr_target_stage: str = "stage"
    gitlab_mr_target_production: str = "main"
    gitlab_verify_ssl: bool = True
    use_mock_gitlab: bool | None = None

    mattermost_url: str = ""
    mattermost_token: str = ""
    mattermost_disaster_channel_id: str = ""
    mattermost_deploy_webhook_url: str = (
        "https://chat.tapsi.food/hooks/n5j5cbj6jjr6jym4utreujr5da"
    )
    gitlab_webhook_secret: str = ""
    deploy_mention: str = "@ebrahimi.mahrokh"
    # Local/dev: poll GitLab when inbound webhooks are unreachable (keep webhook for production)
    deploy_poll_enabled: bool = True
    deploy_poll_interval_seconds: int = 30
    # How many recent successful Stage tag pipelines to scan from GitLab
    deploy_poll_mr_limit: int = 20
    # Max new Deploy Requests (or pipeline_ready upgrades) per sync/poll cycle
    deploy_poll_max_create_per_cycle: int = 10
    # Max items shown in Ready / In progress (newest pipeline first)
    deploy_ready_list_limit: int = 10
    # When true, publish Deploy Request to Mattermost without Tech Lead approval
    deploy_is_automatic_send_message: bool = False

    elasticsearch_url: str = ""
    elasticsearch_username: str = ""
    elasticsearch_password: str = ""
    elasticsearch_index_pattern: str = "app-logs-*"
    elasticsearch_service_name: str = "Dizi"
    elasticsearch_service_environment: str = "Development"
    vendor_service_names: str = "Dizi,dizi"

    knowledge_service_url: str = ""
    knowledge_service_api_key: str = ""
    use_local_knowledge: bool = True
    use_mock_knowledge: bool | None = None
    knowledge_chroma_path: str = "./data/chroma"
    embedding_model: str = "text-embedding-3-small"

    dizi_db_dev_host: str = ""
    dizi_db_dev_port: int = 3306
    dizi_db_dev_user: str = ""
    dizi_db_dev_password: str = ""
    dizi_db_dev_name: str = "dizi_db"
    dizi_db_stage_host: str = ""
    dizi_db_stage_port: int = 3306
    dizi_db_stage_user: str = ""
    dizi_db_stage_password: str = ""
    dizi_db_stage_name: str = "dizi_db"
    dizi_db_connect_timeout_seconds: int = 10

    dizi_repo_path: str = r"C:\Users\jangjoo.ali\source\repos\dizi_new\dizi"
    dizi_src_relative: str = "src"
    dizi_legacy_api_relative: str = "Dizi"
    dizi_spec_branch: str = "dev-oms-v2"
    dizi_specs_storage_path: str = "./data/specs"

    project_dotnet_version: str = "8"

    database_url: str = "sqlite+aiosqlite:///./data/agent_framework.db"
    use_mock_integrations: bool = True

    def should_mock_jira(self) -> bool:
        if self.use_mock_jira is not None:
            return self.use_mock_jira
        return self.use_mock_integrations

    def should_mock_gitlab(self) -> bool:
        if self.use_mock_gitlab is not None:
            return self.use_mock_gitlab
        return self.use_mock_integrations

    def should_mock_knowledge(self) -> bool:
        if self.use_mock_knowledge is not None:
            return self.use_mock_knowledge
        return self.use_mock_integrations


@lru_cache
def get_settings() -> Settings:
    return Settings()
