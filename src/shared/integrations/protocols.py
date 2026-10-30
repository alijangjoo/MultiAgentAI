from abc import ABC, abstractmethod
from typing import Any


class JiraClientProtocol(ABC):
    @abstractmethod
    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_issue_detail(self, issue_key: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def search_issues(
        self,
        project_key: str,
        max_results: int = 50,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def create_subtask(
        self,
        parent_key: str,
        summary: str,
        description: str,
        estimated_hours: float,
    ) -> str:
        pass

    @abstractmethod
    async def create_story(
        self,
        summary: str,
        description: str,
        issue_type: str = "Story",
        labels: list[str] | None = None,
    ) -> str:
        pass

    @abstractmethod
    async def transition_issue(self, issue_key: str, transition_name: str) -> None:
        pass

    @abstractmethod
    async def get_prd_attachment_content(self, issue_key: str) -> str | None:
        pass

    @abstractmethod
    async def get_attachment_contents(self, issue_key: str) -> list[dict[str, Any]]:
        """Return list of {filename, content, mime_type} for task attachments."""
        pass

    @abstractmethod
    async def add_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def add_attachment(self, issue_key: str, filepath: str, filename: str | None = None) -> dict[str, Any]:
        pass


class ConfluenceClientProtocol(ABC):
    @abstractmethod
    async def update_page(
        self,
        page_id: str,
        title: str,
        content: str,
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def create_page(
        self,
        space_key: str,
        title: str,
        content: str,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def search_pages(self, query: str, space_key: str | None = None) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_page_content(self, page_id: str) -> dict[str, Any]:
        pass


class GitLabClientProtocol(ABC):
    @abstractmethod
    async def create_branch(self, branch_name: str, ref: str | None = None) -> dict[str, Any]:
        pass

    @abstractmethod
    async def create_merge_request(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_merge_request(self, mr_iid: int) -> dict[str, Any]:
        pass

    @abstractmethod
    async def list_merge_requests(
        self,
        state: str = "opened",
        limit: int = 50,
        target_branch: str | None = None,
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_merge_request_pipeline_status(self, mr_iid: int) -> dict[str, Any]:
        pass

    @abstractmethod
    async def create_merge_request_note(self, mr_iid: int, body: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def accept_merge_request(
        self,
        mr_iid: int,
        merge_commit_message: str | None = None,
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_merge_request_changes(self, mr_iid: int) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def list_repository_files(
        self,
        ref: str | None = None,
        path: str = "",
        extensions: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_file_content(self, file_path: str, ref: str) -> str:
        pass

    @abstractmethod
    async def commit_files(
        self,
        branch: str,
        commit_message: str,
        files: dict[str, str],
    ) -> dict[str, Any]:
        pass


class MattermostClientProtocol(ABC):
    @abstractmethod
    async def get_channel_posts(
        self,
        channel_id: str,
        since: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def post_message(self, channel_id: str, message: str) -> dict[str, Any]:
        pass


class ElasticsearchClientProtocol(ABC):
    @abstractmethod
    async def search_logs(
        self,
        query: str,
        index_pattern: str | None = None,
        size: int = 50,
        time_range_minutes: int = 60,
        service_name: str | None = None,
        service_environment: str | None = None,
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def search_traces(
        self,
        service_name: str | None = None,
        error: bool = True,
        time_range_minutes: int = 60,
    ) -> list[dict[str, Any]]:
        pass


class KnowledgeServiceProtocol(ABC):
    @abstractmethod
    async def query(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_architecture_context(self, topic: str) -> str:
        pass
