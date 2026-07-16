from typing import Any
from urllib.parse import quote

from shared.integrations.base import run_sync
from shared.integrations.protocols import GitLabClientProtocol


class MockGitLabClient(GitLabClientProtocol):
    _branches: set[str] = set()
    _merge_requests: dict[int, dict[str, Any]] = {}
    _mr_counter = 1
    _seeded = False

    @classmethod
    def _ensure_seed(cls) -> None:
        if cls._seeded:
            return
        cls._seeded = True
        samples = [
            {
                "iid": 1,
                "title": "[VEN-100] Create API for contract",
                "description": "Contract CRUD endpoints",
                "source_branch": "feature/ven-100-create-api-for-contract",
                "target_branch": "develop",
                "web_url": "https://gitlab.company.local/project/-/merge_requests/1",
                "state": "opened",
                "author": "developer@company.local",
                "created_at": "2026-07-01T10:00:00Z",
                "updated_at": "2026-07-04T14:30:00Z",
            },
            {
                "iid": 2,
                "title": "[VEN-101] Add Redis caching layer",
                "description": "Cache-aside for query handlers",
                "source_branch": "feature/ven-101-redis-caching",
                "target_branch": "main",
                "web_url": "https://gitlab.company.local/project/-/merge_requests/2",
                "state": "opened",
                "author": "developer@company.local",
                "created_at": "2026-07-03T09:00:00Z",
                "updated_at": "2026-07-04T11:00:00Z",
            },
            {
                "iid": 3,
                "title": "[VEN-100] Create API for contract",
                "description": "Merged to stage for stg deploy",
                "source_branch": "feature/ven-100-create-api-for-contract",
                "target_branch": "stage",
                "web_url": "https://git.tapsifood.cloud/ofd/backend/dizi/-/merge_requests/3",
                "state": "merged",
                "sha": "aaaa1111",
                "merge_commit_sha": "fbec8be2d9338ca2a716fab3624fe519f2a3fa1f",
                "author": "developer@company.local",
                "created_at": "2026-07-14T09:00:00Z",
                "updated_at": "2026-07-15T10:00:00Z",
            },
        ]
        for mr in samples:
            cls._merge_requests[mr["iid"]] = mr
        cls._mr_counter = max(cls._mr_counter, max(mr["iid"] for mr in samples) + 1)

    async def create_branch(self, branch_name: str, ref: str | None = None) -> dict[str, Any]:
        self._branches.add(branch_name)
        return {"name": branch_name, "ref": ref or "develop", "created": True}

    async def create_merge_request(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        iid = self._mr_counter
        self._mr_counter += 1
        mr = {
            "iid": iid,
            "title": title,
            "description": description,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "web_url": f"https://gitlab.company.local/project/-/merge_requests/{iid}",
            "state": "opened",
        }
        self._merge_requests[iid] = mr
        return mr

    async def get_merge_request(self, mr_iid: int) -> dict[str, Any]:
        self._ensure_seed()
        return self._merge_requests.get(
            mr_iid,
            {"iid": mr_iid, "state": "opened", "web_url": f"https://gitlab.local/mr/{mr_iid}"},
        )

    async def list_merge_requests(
        self,
        state: str = "opened",
        limit: int = 50,
        target_branch: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_seed()
        items = list(self._merge_requests.values())
        if state:
            items = [mr for mr in items if mr.get("state") == state]
        if target_branch:
            items = [mr for mr in items if mr.get("target_branch") == target_branch]
        items.sort(key=lambda m: m.get("updated_at", "") or "", reverse=True)
        return items[:limit]

    async def get_pipeline(self, pipeline_id: int) -> dict[str, Any]:
        for p in self._MOCK_PIPELINES:
            if p["id"] == pipeline_id:
                return dict(p)
        return {
            "id": pipeline_id,
            "iid": pipeline_id,
            "status": "success",
            "ref": "stage",
            "sha": "mock",
            "web_url": f"https://gitlab.company.local/project/-/pipelines/{pipeline_id}",
        }

    async def get_merge_request_changes(self, mr_iid: int) -> list[dict[str, Any]]:
        self._ensure_seed()
        mr = await self.get_merge_request(mr_iid)
        branch = mr.get("source_branch", "feature/mock")
        return [
            {
                "old_path": "src/Application/Contracts/CreateContractHandler.cs",
                "new_path": "src/Application/Contracts/CreateContractHandler.cs",
                "diff": f"// Mock diff for MR !{mr_iid} on branch {branch}\n+ public class CreateContractHandler",
            }
        ]

    async def list_repository_files(
        self,
        ref: str | None = None,
        path: str = "",
        extensions: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        ext = extensions or [".cs", ".md"]
        mock_files = [
            {"path": "docs/adr/001-cqrs-pattern.md", "type": "blob"},
            {"path": "docs/ul/api-overview.md", "type": "blob"},
            {"path": "src/Application/Contracts/CreateContractHandler.cs", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ]
        if path:
            mock_files = [f for f in mock_files if f["path"].startswith(path)]
        if ext:
            mock_files = [
                f for f in mock_files if any(f["path"].lower().endswith(e) for e in ext)
            ]
        return mock_files[:limit]

    async def get_file_content(self, file_path: str, ref: str) -> str:
        return f"// Mock content for {file_path} on {ref}"

    async def commit_files(
        self,
        branch: str,
        commit_message: str,
        files: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "branch": branch,
            "commit_message": commit_message,
            "files_changed": list(files.keys()),
            "committed": True,
        }

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "mode": "mock", "project": "mock-project"}

    async def list_branches(self, search: str | None = None, limit: int = 100) -> list[str]:
        from shared.utils.gitlab_branches import normalize_branch_list

        mock = [
            "main",
            "develop",
            "dev-oms-v2",
            "stage",
            "feature/ven-100-create-api-for-contract",
            "feature/ven-101-redis-caching",
        ]
        if search:
            mock = [b for b in mock if search.lower() in b.lower()]
        return normalize_branch_list(mock)[:limit]

    _MOCK_PIPELINES: list[dict] = [
        {
            "id": 9001,
            "iid": 120,
            "status": "success",
            "ref": "dev-oms-v2",
            "sha": "abc123",
            "web_url": "https://gitlab.company.local/project/-/pipelines/120",
            "created_at": "2026-07-05T10:00:00Z",
            "updated_at": "2026-07-05T10:15:00Z",
        },
        {
            "id": 9002,
            "iid": 121,
            "status": "manual",
            "ref": "main",
            "sha": "def456",
            "web_url": "https://gitlab.company.local/project/-/pipelines/121",
            "created_at": "2026-07-06T08:00:00Z",
            "updated_at": "2026-07-06T08:05:00Z",
        },
        {
            "id": 9003,
            "iid": 122,
            "status": "success",
            "ref": "v2.307.0-stg",
            "tag": True,
            "sha": "fbec8be2d9338ca2a716fab3624fe519f2a3fa1f",
            "web_url": "https://git.tapsifood.cloud/ofd/backend/dizi/-/pipelines/9003",
            "created_at": "2026-07-15T10:00:00Z",
            "updated_at": "2026-07-15T10:20:00Z",
        },
    ]

    _MOCK_JOBS: dict[int, list[dict]] = {
        9001: [
            {"id": 8001, "name": "build", "stage": "build", "status": "success", "web_url": "#", "when": "on_success", "allow_failure": False, "retryable": True},
            {"id": 8002, "name": "test", "stage": "test", "status": "failed", "web_url": "#", "when": "on_success", "allow_failure": False, "retryable": True},
            {"id": 8003, "name": "bump-version", "stage": "deploy", "status": "manual", "web_url": "#", "when": "manual", "allow_failure": False, "retryable": False},
        ],
        9002: [
            {"id": 8004, "name": "build", "stage": "build", "status": "success", "web_url": "#", "when": "on_success", "allow_failure": False, "retryable": True},
            {"id": 8005, "name": "bump-version", "stage": "deploy", "status": "success", "web_url": "#", "when": "manual", "allow_failure": False, "retryable": True},
        ],
        9003: [
            {"id": 8010, "name": "build", "stage": "build", "status": "success", "web_url": "#", "when": "on_success", "allow_failure": False, "retryable": True},
            {"id": 8011, "name": "test", "stage": "test", "status": "success", "web_url": "#", "when": "on_success", "allow_failure": False, "retryable": True},
            {"id": 8012, "name": "bump-version v2.305.0-stg", "stage": "deploy", "status": "success", "web_url": "#", "when": "manual", "allow_failure": False, "retryable": True},
        ],
    }

    async def list_pipelines(
        self,
        ref: str | None = None,
        status: str | None = None,
        limit: int = 30,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        items = list(self._MOCK_PIPELINES)
        if ref:
            items = [p for p in items if p["ref"] == ref]
        if status:
            items = [p for p in items if p["status"] == status]
        if scope == "tags":
            items = [p for p in items if p.get("tag") or str(p.get("ref", "")).startswith("v")]
        return items[:limit]

    async def list_pipeline_jobs(self, pipeline_id: int) -> list[dict[str, Any]]:
        jobs = list(self._MOCK_JOBS.get(pipeline_id, []))
        for job in jobs:
            job.setdefault(
                "retryable",
                job.get("status") in ("success", "failed", "canceled", "skipped"),
            )
        return jobs

    async def play_job(
        self,
        job_id: int,
        variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        for jobs in self._MOCK_JOBS.values():
            for job in jobs:
                if job["id"] == job_id:
                    if job["status"] != "manual":
                        raise ValueError(f"Job {job_id} is not manual (status={job['status']})")
                    job["status"] = "pending"
                    return {
                        "id": job_id,
                        "name": job["name"],
                        "status": "pending",
                        "variables": variables or [],
                        "web_url": job.get("web_url"),
                        "message": f"Job {job['name']} started",
                    }
        raise ValueError(f"Job {job_id} not found")

    async def retry_job(
        self,
        job_id: int,
        variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        for jobs in self._MOCK_JOBS.values():
            for job in jobs:
                if job["id"] == job_id:
                    status = job["status"]
                    if status == "manual":
                        raise ValueError(f"Job {job_id} is manual — use Play instead of Retry")
                    if status not in ("success", "failed", "canceled", "skipped"):
                        raise ValueError(f"Job {job_id} is not retryable (status={status})")
                    job["status"] = "pending"
                    return {
                        "id": job_id,
                        "name": job["name"],
                        "status": "pending",
                        "variables": variables or [],
                        "web_url": job.get("web_url"),
                        "message": f"Job {job['name']} retried",
                    }
        raise ValueError(f"Job {job_id} not found")

    async def create_pipeline(
        self,
        ref: str,
        variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        pipeline_id = 9100 + len(self._MOCK_PIPELINES)
        pipeline = {
            "id": pipeline_id,
            "iid": pipeline_id,
            "status": "running",
            "ref": ref,
            "sha": "mocksha",
            "web_url": f"https://gitlab.company.local/project/-/pipelines/{pipeline_id}",
            "created_at": None,
            "updated_at": None,
            "variables": variables or [],
        }
        self._MOCK_PIPELINES.insert(0, pipeline)
        self._MOCK_JOBS[pipeline_id] = [
            {
                "id": 8100 + pipeline_id,
                "name": "bump-version",
                "stage": "deploy",
                "status": "manual",
                "web_url": "#",
                "when": "manual",
                "allow_failure": False,
                "retryable": False,
            }
        ]
        return pipeline


class RealGitLabClient(GitLabClientProtocol):
    """
    On-premise GitLab client.

    Project lookup supports numeric ID (GITLAB_PROJECT_ID) or path (GITLAB_PROJECT_PATH).
    Set GITLAB_VERIFY_SSL=false for internal/self-signed certificates.
    """

    def __init__(
        self,
        url: str,
        token: str,
        project_id: int | None = None,
        project_path: str | None = None,
        default_branch: str = "develop",
        verify_ssl: bool = True,
    ):
        import gitlab

        if not url or not token:
            raise ValueError("GITLAB_URL and GITLAB_TOKEN are required")
        if not project_id and not project_path:
            raise ValueError("Set GITLAB_PROJECT_ID or GITLAB_PROJECT_PATH")

        self._url = url.rstrip("/")
        self._token = token
        self._default_branch = default_branch
        self._verify_ssl = verify_ssl
        self._project_ref = project_id if project_id else quote(project_path or "", safe="")

        self._gl = gitlab.Gitlab(
            url=self._url,
            private_token=self._token,
            ssl_verify=self._verify_ssl,
        )
        self._project = None

    def _ensure_connected(self) -> None:
        if self._project is not None:
            return
        self._gl.auth()
        self._project = self._gl.projects.get(self._project_ref)

    @staticmethod
    def _retryable_statuses() -> frozenset[str]:
        return frozenset({"success", "failed", "canceled", "skipped"})

    @classmethod
    def _job_is_retryable(cls, status: str, retryable: bool | None = None) -> bool:
        if retryable is not None:
            return retryable
        return status in cls._retryable_statuses()

    @staticmethod
    def _variables_post_data(variables: list[dict[str, str]] | None) -> dict[str, Any]:
        if not variables:
            return {}
        return {
            "job_variables_attributes": [
                {"key": v["key"], "value": str(v["value"])} for v in variables
            ]
        }

    def _project_info(self) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        return {
            "id": self._project.id,
            "name": self._project.name,
            "path_with_namespace": self._project.path_with_namespace,
            "web_url": self._project.web_url,
            "default_branch": self._project.default_branch,
        }
        self._ensure_connected()
        assert self._project is not None
        return {
            "id": self._project.id,
            "name": self._project.name,
            "path_with_namespace": self._project.path_with_namespace,
            "web_url": self._project.web_url,
            "default_branch": self._project.default_branch,
        }

    def _create_branch_sync(self, branch_name: str, ref: str | None) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        base_ref = ref or self._default_branch or self._project.default_branch
        try:
            branch = self._project.branches.create({"branch": branch_name, "ref": base_ref})
            return {"name": branch.name, "ref": base_ref, "created": True}
        except Exception as exc:
            if "already exists" in str(exc).lower():
                return {"name": branch_name, "ref": base_ref, "created": False, "exists": True}
            raise

    async def create_branch(self, branch_name: str, ref: str | None = None) -> dict[str, Any]:
        return await run_sync(self._create_branch_sync, branch_name, ref)

    def _create_mr_sync(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        mr = self._project.mergerequests.create(
            {
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
                "remove_source_branch": True,
            }
        )
        return {
            "iid": mr.iid,
            "title": mr.title,
            "description": mr.description,
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
            "web_url": mr.web_url,
            "state": mr.state,
        }

    async def create_merge_request(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        return await run_sync(
            self._create_mr_sync,
            source_branch,
            target_branch,
            title,
            description,
        )

    def _get_mr_sync(self, mr_iid: int) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        mr = self._project.mergerequests.get(mr_iid)
        return {
            "iid": mr.iid,
            "title": mr.title,
            "description": getattr(mr, "description", "") or "",
            "state": mr.state,
            "web_url": mr.web_url,
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
            "sha": getattr(mr, "sha", None),
            "merge_commit_sha": getattr(mr, "merge_commit_sha", None),
        }

    async def get_merge_request(self, mr_iid: int) -> dict[str, Any]:
        return await run_sync(self._get_mr_sync, mr_iid)

    def _list_mrs_sync(
        self,
        state: str,
        limit: int,
        target_branch: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_connected()
        assert self._project is not None
        kwargs: dict[str, Any] = {
            "state": state,
            "order_by": "updated_at",
            "sort": "desc",
            "per_page": limit,
        }
        if target_branch:
            kwargs["target_branch"] = target_branch
        mrs = self._project.mergerequests.list(**kwargs)
        return [
            {
                "iid": mr.iid,
                "title": mr.title,
                "description": getattr(mr, "description", "") or "",
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "web_url": mr.web_url,
                "state": mr.state,
                "sha": getattr(mr, "sha", None),
                "merge_commit_sha": getattr(mr, "merge_commit_sha", None),
                "author": getattr(getattr(mr, "author", None), "username", None),
                "created_at": getattr(mr, "created_at", None),
                "updated_at": getattr(mr, "updated_at", None),
            }
            for mr in mrs
        ]

    async def list_merge_requests(
        self,
        state: str = "opened",
        limit: int = 50,
        target_branch: str | None = None,
    ) -> list[dict[str, Any]]:
        return await run_sync(self._list_mrs_sync, state, limit, target_branch)

    def _get_pipeline_sync(self, pipeline_id: int) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        pipeline = self._project.pipelines.get(pipeline_id)
        return {
            "id": pipeline.id,
            "iid": getattr(pipeline, "iid", pipeline.id),
            "status": pipeline.status,
            "ref": pipeline.ref,
            "sha": getattr(pipeline, "sha", ""),
            "web_url": pipeline.web_url,
            "created_at": getattr(pipeline, "created_at", None),
            "updated_at": getattr(pipeline, "updated_at", None),
        }

    async def get_pipeline(self, pipeline_id: int) -> dict[str, Any]:
        return await run_sync(self._get_pipeline_sync, pipeline_id)

    def _get_mr_changes_sync(self, mr_iid: int) -> list[dict[str, Any]]:
        self._ensure_connected()
        assert self._project is not None
        mr = self._project.mergerequests.get(mr_iid)
        changes_payload = mr.changes()
        result = []
        for change in changes_payload.get("changes", []):
            result.append(
                {
                    "old_path": change.get("old_path"),
                    "new_path": change.get("new_path"),
                    "diff": (change.get("diff") or "")[:4000],
                }
            )
        return result

    async def get_merge_request_changes(self, mr_iid: int) -> list[dict[str, Any]]:
        return await run_sync(self._get_mr_changes_sync, mr_iid)

    def _list_repository_files_sync(
        self,
        ref: str | None,
        path: str,
        extensions: list[str] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        self._ensure_connected()
        assert self._project is not None
        base_ref = ref or self._default_branch or self._project.default_branch
        ext_set = {e.lower() for e in (extensions or [".cs", ".md"])}
        items: list[dict[str, Any]] = []
        tree = self._project.repository_tree(
            path=path,
            ref=base_ref,
            recursive=True,
            per_page=100,
            get_all=True,
        )
        for item in tree:
            if item.get("type") != "blob":
                continue
            item_path = item.get("path", "")
            if ext_set and not any(item_path.lower().endswith(ext) for ext in ext_set):
                continue
            items.append({"path": item_path, "type": item.get("type", "blob")})
            if len(items) >= limit:
                break
        return items

    async def list_repository_files(
        self,
        ref: str | None = None,
        path: str = "",
        extensions: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return await run_sync(
            self._list_repository_files_sync,
            ref,
            path,
            extensions,
            limit,
        )

    def _get_file_sync(self, file_path: str, ref: str) -> str:
        self._ensure_connected()
        assert self._project is not None
        file_obj = self._project.files.get(file_path=file_path, ref=ref)
        return file_obj.decode().decode("utf-8")

    async def get_file_content(self, file_path: str, ref: str) -> str:
        return await run_sync(self._get_file_sync, file_path, ref)

    def _file_exists_sync(self, file_path: str, ref: str) -> bool:
        self._ensure_connected()
        assert self._project is not None
        try:
            self._project.files.get(file_path=file_path, ref=ref)
            return True
        except Exception:
            return False

    def _commit_files_sync(
        self,
        branch: str,
        commit_message: str,
        files: dict[str, str],
    ) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        actions = []
        for path, content in files.items():
            action = "update" if self._file_exists_sync(path, branch) else "create"
            actions.append({"action": action, "file_path": path, "content": content})

        commit = self._project.commits.create(
            {"branch": branch, "commit_message": commit_message, "actions": actions}
        )
        return {
            "id": commit.id,
            "branch": branch,
            "committed": True,
            "files_changed": list(files.keys()),
        }

    async def commit_files(
        self,
        branch: str,
        commit_message: str,
        files: dict[str, str],
    ) -> dict[str, Any]:
        return await run_sync(self._commit_files_sync, branch, commit_message, files)

    def _list_branches_sync(self, search: str | None = None, limit: int = 100) -> list[str]:
        self._ensure_connected()
        assert self._project is not None
        kwargs: dict = {"per_page": 100, "get_all": True}
        if search:
            kwargs["search"] = search
            kwargs.pop("get_all", None)
            kwargs["per_page"] = min(limit, 100)
        branches = self._project.branches.list(**kwargs)
        names = [branch.name for branch in branches]
        if search:
            return names[:limit]
        return names

    async def list_branches(self, search: str | None = None, limit: int = 100) -> list[str]:
        return await run_sync(self._list_branches_sync, search, limit)

    def _list_pipelines_sync(
        self,
        ref: str | None,
        status: str | None,
        limit: int,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_connected()
        assert self._project is not None
        kwargs: dict = {"per_page": min(limit, 100), "order_by": "id", "sort": "desc"}
        if ref:
            kwargs["ref"] = ref
        if status:
            kwargs["status"] = status
        if scope:
            kwargs["scope"] = scope
        pipelines = self._project.pipelines.list(**kwargs)
        return [
            {
                "id": p.id,
                "iid": p.iid,
                "status": p.status,
                "ref": p.ref,
                "tag": bool(getattr(p, "tag", False)),
                "sha": getattr(p, "sha", ""),
                "web_url": p.web_url,
                "created_at": getattr(p, "created_at", None),
                "updated_at": getattr(p, "updated_at", None),
            }
            for p in pipelines
        ]

    async def list_pipelines(
        self,
        ref: str | None = None,
        status: str | None = None,
        limit: int = 30,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        return await run_sync(self._list_pipelines_sync, ref, status, limit, scope)

    def _list_pipeline_jobs_sync(self, pipeline_id: int) -> list[dict[str, Any]]:
        self._ensure_connected()
        assert self._project is not None
        pipeline = self._project.pipelines.get(pipeline_id)
        jobs = pipeline.jobs.list(all=True)
        return [
            {
                "id": job.id,
                "name": job.name,
                "stage": job.stage,
                "status": job.status,
                "web_url": job.web_url,
                "when": getattr(job, "when", None),
                "allow_failure": getattr(job, "allow_failure", False),
                "retryable": self._job_is_retryable(
                    job.status,
                    getattr(job, "retryable", None),
                ),
            }
            for job in jobs
        ]

    async def list_pipeline_jobs(self, pipeline_id: int) -> list[dict[str, Any]]:
        return await run_sync(self._list_pipeline_jobs_sync, pipeline_id)

    def _play_job_sync(
        self,
        job_id: int,
        variables: list[dict[str, str]] | None,
    ) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        job = self._project.jobs.get(job_id)
        if job.status != "manual":
            raise ValueError(f"Job {job_id} is not manual (status={job.status})")

        # GitLab play API expects JSON body with only key/value pairs (no variable_type).
        # Use http_post directly so kwargs are never sent as query params.
        path = f"/projects/{self._project.encoded_id}/jobs/{job_id}/play"
        post_data = self._variables_post_data(variables)

        result = self._gl.http_post(path, post_data=post_data or None)
        if isinstance(result, dict):
            job_status = result.get("status", "pending")
            job_name = result.get("name", job.name)
            job_web_url = result.get("web_url", job.web_url)
            job_id_out = result.get("id", job.id)
        else:
            job.refresh()
            job_status = job.status
            job_name = job.name
            job_web_url = job.web_url
            job_id_out = job.id

        return {
            "id": job_id_out,
            "name": job_name,
            "status": job_status,
            "variables": variables or [],
            "web_url": job_web_url,
            "message": f"Job {job_name} started",
        }

    async def play_job(
        self,
        job_id: int,
        variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return await run_sync(self._play_job_sync, job_id, variables)

    def _retry_job_sync(
        self,
        job_id: int,
        variables: list[dict[str, str]] | None,
    ) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        job = self._project.jobs.get(job_id)
        retryable = self._job_is_retryable(job.status, getattr(job, "retryable", None))
        if not retryable:
            if job.status == "manual":
                raise ValueError(f"Job {job_id} is manual — use Play instead of Retry")
            raise ValueError(f"Job {job_id} is not retryable (status={job.status})")

        path = f"/projects/{self._project.encoded_id}/jobs/{job_id}/retry"
        post_data = self._variables_post_data(variables)

        result = self._gl.http_post(path, post_data=post_data or None)
        if isinstance(result, dict):
            return {
                "id": result.get("id", job.id),
                "name": result.get("name", job.name),
                "status": result.get("status", "pending"),
                "variables": variables or [],
                "web_url": result.get("web_url", job.web_url),
                "message": f"Job {result.get('name', job.name)} retried",
            }

        job.refresh()
        return {
            "id": job.id,
            "name": job.name,
            "status": job.status,
            "variables": variables or [],
            "web_url": job.web_url,
            "message": f"Job {job.name} retried",
        }

    async def retry_job(
        self,
        job_id: int,
        variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return await run_sync(self._retry_job_sync, job_id, variables)

    def _create_pipeline_sync(
        self,
        ref: str,
        variables: list[dict[str, str]] | None,
    ) -> dict[str, Any]:
        self._ensure_connected()
        assert self._project is not None
        kwargs: dict[str, Any] = {"ref": ref}
        if variables:
            kwargs["variables"] = [
                {"key": v["key"], "value": str(v["value"])} for v in variables if v.get("key")
            ]
        pipeline = self._project.pipelines.create(kwargs)
        return {
            "id": pipeline.id,
            "iid": getattr(pipeline, "iid", pipeline.id),
            "status": pipeline.status,
            "ref": pipeline.ref,
            "sha": getattr(pipeline, "sha", ""),
            "web_url": pipeline.web_url,
            "created_at": getattr(pipeline, "created_at", None),
            "updated_at": getattr(pipeline, "updated_at", None),
            "variables": variables or [],
        }

    async def create_pipeline(
        self,
        ref: str,
        variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return await run_sync(self._create_pipeline_sync, ref, variables)

    def _test_connection_sync(self) -> dict[str, Any]:
        self._ensure_connected()
        user = self._gl.user
        return {
            "ok": True,
            "mode": "real",
            "url": self._url,
            "user": getattr(user, "username", None) or getattr(user, "name", None),
            "project": self._project_info(),
        }

    async def test_connection(self) -> dict[str, Any]:
        try:
            return await run_sync(self._test_connection_sync)
        except Exception as exc:
            return {"ok": False, "mode": "real", "url": self._url, "error": str(exc)}
