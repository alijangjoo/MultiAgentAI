from pydantic import BaseModel, Field

from slices.knowledge.models.collections import KnowledgeCollection


class KnowledgeQueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    collections: list[KnowledgeCollection] | None = Field(
        default=None,
        description="Limit search to specific collections; searches all if omitted",
    )
    top_k: int = Field(default=5, ge=1, le=20)
    synthesize: bool = Field(
        default=True,
        description="Use Knowledge Agent to synthesize an answer from retrieved chunks",
    )
    context: dict = Field(default_factory=dict)


class KnowledgeQueryResultItem(BaseModel):
    id: str
    content: str
    score: float
    collection: str
    title: str | None = None
    metadata: dict = Field(default_factory=dict)


class KnowledgeQueryResponse(BaseModel):
    question: str
    answer: str | None = None
    results: list[KnowledgeQueryResultItem]
    collections_searched: list[str]
    run_id: str | None = None


class KnowledgeIngestRequest(BaseModel):
    collection: KnowledgeCollection
    title: str = Field(..., min_length=2)
    content: str = Field(..., min_length=10)
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    task_key: str | None = None


class KnowledgeIngestResponse(BaseModel):
    id: str
    collection: str
    title: str
    chunks_created: int
    message: str


class KnowledgeDocumentItem(BaseModel):
    id: str
    collection: str
    title: str
    content_preview: str
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    task_key: str | None = None
    created_at: str | None = None


class KnowledgeStatsResponse(BaseModel):
    total_documents: int
    total_chunks: int
    collections: dict[str, int]
    chroma_path: str
    embedding_model: str


class SpecListItem(BaseModel):
    spec_id: str
    title: str
    structure_tag: str
    source_kind: str
    source_path: str
    bounded_context: str | None = None
    tags: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class SpecDetailResponse(BaseModel):
    spec_id: str
    frontmatter: dict
    body: str
    markdown: str


class SpecUpdateRequest(BaseModel):
    body: str = Field(..., min_length=10)
    sync_knowledge: bool = True


class SpecScanRequest(BaseModel):
    repo_path: str | None = None
    branch: str | None = None
    sync_knowledge: bool = True


class SpecScanResponse(BaseModel):
    run_id: str
    specs_generated: int
    specs_synced: int
    spec_ids: list[str]
    message: str


class SpecSyncResponse(BaseModel):
    specs_synced: int
    message: str


class KnowledgeRunSummary(BaseModel):
    id: str
    workflow_type: str
    status: str
    created_at: str
    updated_at: str
    question: str | None = None
    source: str | None = None
    documents_ingested: int | None = None
    chunks_created: int | None = None
    answer_preview: str | None = None
    error_message: str | None = None


class KnowledgeEventItem(BaseModel):
    id: str
    run_id: str
    event_type: str
    message: str
    created_at: str
    payload: dict = Field(default_factory=dict)


class KnowledgeMonitoringResponse(BaseModel):
    stats: KnowledgeStatsResponse
    collections: list[dict]
    run_summary: dict[str, int]
    recent_runs: list[KnowledgeRunSummary]
    recent_events: list[KnowledgeEventItem]
    chroma_healthy: bool = True
