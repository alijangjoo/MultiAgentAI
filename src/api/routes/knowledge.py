from fastapi import APIRouter, HTTPException, Query

from slices.knowledge.models.collections import COLLECTION_LABELS, KnowledgeCollection
from slices.knowledge.models.schemas import (
    KnowledgeDocumentItem,
    KnowledgeIngestRequest,
    KnowledgeIngestResponse,
    KnowledgeMonitoringResponse,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeStatsResponse,
    SpecDetailResponse,
    SpecListItem,
    SpecScanRequest,
    SpecScanResponse,
    SpecSyncResponse,
    SpecUpdateRequest,
)
from slices.knowledge.ingest.service import KnowledgeIngestService
from slices.knowledge.monitoring import KnowledgeMonitoringService
from slices.knowledge.service import KnowledgeRAGService
from slices.knowledge.specs.service import ArchitectureSpecService

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

_service: KnowledgeRAGService | None = None
_ingest_service: KnowledgeIngestService | None = None
_monitoring_service: KnowledgeMonitoringService | None = None
_spec_service: ArchitectureSpecService | None = None


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


def _get_spec_service() -> ArchitectureSpecService:
    global _spec_service
    if _spec_service is None:
        _spec_service = ArchitectureSpecService()
    return _spec_service


@router.get("/monitoring", response_model=KnowledgeMonitoringResponse)
async def knowledge_monitoring(runs_limit: int = Query(default=30, ge=1, le=100)):
    """Full monitoring snapshot for Sage Knowledge Agent dashboard."""
    return await _get_monitoring_service().get_monitoring_snapshot(runs_limit=runs_limit)


@router.get("/runs/{run_id}")
async def get_knowledge_run(run_id: str):
    detail = await _get_monitoring_service().get_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Sage run not found")
    return detail


@router.get("/documents/{doc_id}/detail")
async def get_document_detail(doc_id: str):
    doc = _get_monitoring_service().get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge(request: KnowledgeQueryRequest):
    """Query knowledge via Sage RAG agent (retrieval + optional synthesis)."""
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
    try:
        result = await _get_ingest_service().ingest_local_docs(docs_root=docs_root)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "source": result["source"],
        "documents_ingested": result["documents_ingested"],
        "chunks_created": result["chunks_created"],
        "message": f"Ingested {result['documents_ingested']} local markdown files",
    }


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
    path = _get_spec_service().get_template_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="SPEC_TEMPLATE.md not found")
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")


@router.get("/specs", response_model=list[SpecListItem])
async def list_architecture_specs(
    structure_tag: str | None = Query(default=None, description="new-structure | legacy-api"),
):
    items = _get_spec_service().list_specs(structure_tag=structure_tag)
    return [SpecListItem(**item) for item in items]


@router.post("/specs/scan", response_model=SpecScanResponse)
async def scan_architecture_specs(request: SpecScanRequest | None = None):
    req = request or SpecScanRequest()
    try:
        result = await _get_spec_service().scan_from_source(
            repo_path=req.repo_path,
            branch=req.branch,
            sync_knowledge=req.sync_knowledge,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SpecScanResponse(**result)


@router.post("/specs/sync", response_model=SpecSyncResponse)
async def sync_specs_to_knowledge():
    count = _get_spec_service().sync_all_to_knowledge()
    return SpecSyncResponse(
        specs_synced=count,
        message=f"Synced {count} specs to ChromaDB (architecture_spec collection)",
    )


@router.get("/specs/{spec_id:path}", response_model=SpecDetailResponse)
async def get_architecture_spec(spec_id: str):
    try:
        return SpecDetailResponse(**_get_spec_service().get_spec(spec_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/specs/{spec_id:path}", response_model=SpecDetailResponse)
async def update_architecture_spec(spec_id: str, request: SpecUpdateRequest):
    try:
        return SpecDetailResponse(
            **_get_spec_service().update_spec(
                spec_id,
                request.body,
                sync_knowledge=request.sync_knowledge,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
