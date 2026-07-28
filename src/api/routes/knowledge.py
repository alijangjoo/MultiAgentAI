from fastapi import APIRouter, HTTPException, Query

from slices.knowledge.models.collections import COLLECTION_LABELS, KnowledgeCollection
from slices.knowledge.database_sync import (
    DatabaseEnvironment,
    DatabaseKnowledgeSyncService,
    DatabaseSyncError,
)
from slices.knowledge.models.schemas import (
    KnowledgeDocumentItem,
    KnowledgeIngestRequest,
    KnowledgeIngestResponse,
    KnowledgeMonitoringResponse,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeStatsResponse,
    SpecScanRequest,
    SpecSyncResponse,
    SpecUpdateRequest,
)
from pydantic import BaseModel, Field

from slices.knowledge.ingest.service import KnowledgeIngestService
from slices.knowledge.monitoring import KnowledgeMonitoringService
from slices.knowledge.review_docs import get_review_docs_service
from slices.knowledge.service import KnowledgeRAGService

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

_service: KnowledgeRAGService | None = None
_ingest_service: KnowledgeIngestService | None = None
_monitoring_service: KnowledgeMonitoringService | None = None
_database_sync_service: DatabaseKnowledgeSyncService | None = None


class ReviewPromptUpdateRequest(BaseModel):
    body: str = Field(..., min_length=20)


class ManagedReviewDocumentRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., min_length=20)
    doc_id: str | None = Field(default=None, min_length=2, max_length=200)


class UlSyncRequest(BaseModel):
    path: str = Field(..., min_length=3)


def _get_service() -> KnowledgeRAGService:
    global _service
    if _service is None:
        _service = KnowledgeRAGService()
    return _service


def _get_ingest_service() -> KnowledgeIngestService:
    global _ingest_service
    if _ingest_service is None:
        _ingest_service = KnowledgeIngestService()
    return _ingest_service


def _get_monitoring_service() -> KnowledgeMonitoringService:
    global _monitoring_service
    if _monitoring_service is None:
        _monitoring_service = KnowledgeMonitoringService()
    return _monitoring_service


def _get_database_sync_service() -> DatabaseKnowledgeSyncService:
    global _database_sync_service
    if _database_sync_service is None:
        _database_sync_service = DatabaseKnowledgeSyncService()
    return _database_sync_service


@router.get("/monitoring", response_model=KnowledgeMonitoringResponse)
async def knowledge_monitoring(runs_limit: int = Query(default=30, ge=1, le=100)):
    """Full monitoring snapshot for the Knowledge Agent dashboard."""
    return await _get_monitoring_service().get_monitoring_snapshot(runs_limit=runs_limit)


@router.get("/runs/{run_id}")
async def get_knowledge_run(run_id: str):
    detail = await _get_monitoring_service().get_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Knowledge Agent run not found")
    return detail


@router.get("/documents/{doc_id}/detail")
async def get_document_detail(doc_id: str):
    doc = _get_monitoring_service().get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge(request: KnowledgeQueryRequest):
    """Query through the Knowledge Agent (retrieval + optional synthesis)."""
    try:
        return await _get_service().query(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ingest", response_model=KnowledgeIngestResponse)
async def ingest_document(request: KnowledgeIngestRequest):
    """Add a document to a knowledge collection."""
    try:
        return await _get_service().ingest(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/documents", response_model=list[KnowledgeDocumentItem])
async def list_documents(
    collection: KnowledgeCollection | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    docs = _get_service().list_documents(
        collection=collection.value if collection else None,
        limit=limit,
    )
    return [KnowledgeDocumentItem(**d) for d in docs]


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    deleted = _get_service().delete_document(doc_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted_chunks": deleted, "doc_id": doc_id}


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def knowledge_stats():
    return _get_service().get_stats()


@router.get("/collections")
async def list_collections():
    return {
        "collections": [
            {"id": key, "label": label}
            for key, label in COLLECTION_LABELS.items()
        ]
    }


@router.get("/database/environments")
async def list_database_environments():
    return {
        "collection": KnowledgeCollection.DATABASE_SCHEMA.value,
        "data_policy": "Schema metadata only; application row values are never stored.",
        "environments": _get_database_sync_service().list_environments(),
    }


@router.post("/database/{environment}/test")
async def test_database_connection(environment: DatabaseEnvironment):
    return await _get_database_sync_service().connection_status(
        environment,
        test=True,
    )


@router.post("/database/{environment}/sync")
async def sync_database_schema(environment: DatabaseEnvironment):
    try:
        return await _get_database_sync_service().sync(environment)
    except DatabaseSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/database/{environment}")
async def purge_database_schema(environment: DatabaseEnvironment):
    return _get_database_sync_service().purge(environment)


@router.post("/ingest/gitlab")
async def ingest_from_gitlab(
    ref: str | None = None,
    path: str = "",
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        result = await _get_ingest_service().ingest_gitlab(ref=ref, path=path, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "source": result["source"],
        "documents_ingested": result["documents_ingested"],
        "chunks_created": result["chunks_created"],
        "message": f"Ingested {result['documents_ingested']} files from GitLab",
    }


@router.post("/ingest/dizi-main")
async def ingest_dizi_main(
    ref: str = Query(default="main"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """Scan Dizi project on the given branch (default main) into Knowledge."""
    try:
        result = await _get_ingest_service().ingest_gitlab(ref=ref, path="", limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        **result,
        "message": (
            f"Scanned Dizi @{ref}: ingested {result['documents_ingested']} files "
            f"({result['chunks_created']} chunks)"
        ),
    }


@router.get("/review-docs/rules")
async def list_review_rules():
    return {"items": get_review_docs_service().list_review_rule_files()}


@router.post("/review-docs/rules/sync")
async def sync_review_rules():
    return get_review_docs_service().sync_review_rules()


@router.get("/review-docs/specs")
async def list_code_specs():
    return {"items": get_review_docs_service().list_code_spec_files()}


@router.post("/review-docs/specs/sync")
async def sync_code_specs():
    return get_review_docs_service().sync_code_specs()


@router.get("/review-docs/managed/{kind}")
async def list_managed_review_documents(kind: str):
    try:
        return {
            "kind": kind,
            "source": "chroma",
            "items": get_review_docs_service().list_managed_documents(kind),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/review-docs/managed/{kind}")
async def create_managed_review_document(
    kind: str, body: ManagedReviewDocumentRequest
):
    try:
        return get_review_docs_service().upsert_managed_document(
            kind,
            title=body.title,
            content=body.content,
            doc_id=body.doc_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/review-docs/managed/{kind}/{doc_id}")
async def update_managed_review_document(
    kind: str, doc_id: str, body: ManagedReviewDocumentRequest
):
    try:
        return get_review_docs_service().upsert_managed_document(
            kind,
            title=body.title,
            content=body.content,
            doc_id=doc_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/review-docs/managed/{kind}/{doc_id}")
async def delete_managed_review_document(kind: str, doc_id: str):
    try:
        deleted = get_review_docs_service().delete_managed_document(kind, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Managed document not found")
    return {"kind": kind, "doc_id": doc_id, "deleted_chunks": deleted}


@router.get("/review-docs/ul")
async def list_ul_documents():
    return {"items": get_review_docs_service().list_ul_files()}


@router.post("/review-docs/ul/sync")
async def sync_ul_document(body: UlSyncRequest):
    try:
        return get_review_docs_service().sync_ul_file(body.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/review-docs/ul/sync-all")
async def sync_all_ul_documents():
    return get_review_docs_service().sync_all_ul()


@router.get("/review-prompt")
async def get_review_prompt_template():
    return get_review_docs_service().get_prompt_template()


@router.put("/review-prompt")
async def update_review_prompt_template(body: ReviewPromptUpdateRequest):
    try:
        return get_review_docs_service().save_prompt_template(body.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/review-skill")
async def get_review_skill():
    return get_review_docs_service().get_review_skill()


@router.put("/review-skill")
async def update_review_skill(body: ReviewPromptUpdateRequest):
    try:
        return get_review_docs_service().save_review_skill(body.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review-skill/sync-from-rules")
async def sync_review_skill_from_rules():
    try:
        return get_review_docs_service().sync_review_skill_from_active_rules()
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ingest/confluence")
async def ingest_from_confluence(
    query: str = Query(default="API"),
    space_key: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        result = await _get_ingest_service().ingest_confluence(
            query=query,
            space_key=space_key,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "source": result["source"],
        "documents_ingested": result["documents_ingested"],
        "chunks_created": result["chunks_created"],
        "message": f"Ingested {result['documents_ingested']} pages from Confluence",
    }


@router.post("/ingest/local")
async def ingest_local_docs(docs_root: str | None = None):
    del docs_root
    raise HTTPException(
        status_code=410,
        detail=(
            "Local-file ingestion is disabled. Create or update documents through "
            "the Chroma-backed Knowledge document APIs."
        ),
    )


@router.post("/ingest/merge-request/{mr_iid}")
async def ingest_merge_request(mr_iid: int):
    try:
        result = await _get_ingest_service().ingest_merge_request(mr_iid)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "source": result["source"],
        "documents_ingested": result["documents_ingested"],
        "chunks_created": result["chunks_created"],
        "message": f"MR !{mr_iid} ingested into knowledge base",
    }


@router.get("/specs/template")
async def get_spec_template():
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(
        "# Architecture Spec\n\nEdit architecture specs in the Knowledge dashboard. "
        "The source of truth is the ChromaDB `architecture_spec` collection.\n",
        media_type="text/markdown",
    )


@router.get("/specs")
async def list_architecture_specs(
    structure_tag: str | None = Query(default=None, description="new-structure | legacy-api"),
):
    del structure_tag
    return get_review_docs_service().list_managed_documents("architecture-specs")


@router.post("/specs/scan")
async def scan_architecture_specs(request: SpecScanRequest | None = None):
    del request
    raise HTTPException(
        status_code=410,
        detail="Filesystem spec scanning is disabled; edit Chroma documents directly.",
    )


@router.post("/specs/sync", response_model=SpecSyncResponse)
async def sync_specs_to_knowledge():
    return SpecSyncResponse(
        specs_synced=0,
        message="Architecture specs are already stored directly in ChromaDB.",
    )


@router.get("/specs/{spec_id:path}")
async def get_architecture_spec(spec_id: str):
    item = next(
        (
            row
            for row in get_review_docs_service().list_managed_documents(
                "architecture-specs"
            )
            if row["id"] == spec_id
        ),
        None,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Architecture spec not found")
    return {
        "spec_id": item["id"],
        "frontmatter": {"title": item["title"], "source_kind": "chroma"},
        "body": item["content"],
        "markdown": item["content"],
    }


@router.put("/specs/{spec_id:path}")
async def update_architecture_spec(spec_id: str, request: SpecUpdateRequest):
    existing = await get_architecture_spec(spec_id)
    saved = get_review_docs_service().upsert_managed_document(
        "architecture-specs",
        doc_id=spec_id,
        title=existing["frontmatter"]["title"],
        content=request.body,
    )
    return {
        "spec_id": saved["id"],
        "frontmatter": {"title": saved["title"], "source_kind": "chroma"},
        "body": saved["content"],
        "markdown": saved["content"],
    }
