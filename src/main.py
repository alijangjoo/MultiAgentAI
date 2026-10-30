from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes.deploy_settings import router as deploy_settings_router
from api.routes.deploy_requests import router as deploy_requests_router
from api.routes.agent_settings import router as agent_settings_router
from api.routes.agents import router as agents_router
from api.routes.dashboard_ws import router as ws_router
from api.routes.integrations import router as integrations_router
from api.routes.gitlab_pipelines import router as gitlab_pipelines_router
from api.routes.gitlab_mrs import router as gitlab_mrs_router
from api.routes.gitlab_webhooks import router as gitlab_webhooks_router
from api.routes.jira_tasks import router as jira_tasks_router
from api.routes.knowledge import router as knowledge_router
from api.routes.product_manager import router as product_manager_router
from api.routes.qa import router as qa_router
from api.routes.rtk import router as rtk_router
from core.config import get_settings
from core.logging import configure_logging
from core.tracing import flush_tracing, init_tracing, tracing_status
from shared.persistence.database import init_db
from slices.deploy_request.poller import start_deploy_poller, stop_deploy_poller

DASHBOARD_DIR = Path(__file__).resolve().parent / "dashboard" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().debug)
    init_tracing()
    await init_db()
    start_deploy_poller()
    try:
        yield
    finally:
        flush_tracing()
        await stop_deploy_poller()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Multi-Agent SDLC Orchestration Platform with LangGraph and HITL",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(agents_router)
    app.include_router(agent_settings_router)
    app.include_router(deploy_settings_router)
    app.include_router(deploy_requests_router)
    app.include_router(integrations_router)
    app.include_router(jira_tasks_router)
    app.include_router(gitlab_mrs_router)
    app.include_router(gitlab_pipelines_router)
    app.include_router(gitlab_webhooks_router)
    app.include_router(knowledge_router)
    app.include_router(product_manager_router)
    app.include_router(rtk_router)
    app.include_router(qa_router)
    app.include_router(ws_router)

    if DASHBOARD_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        home = DASHBOARD_DIR / "home.html"
        if home.exists():
            return FileResponse(str(home), media_type="text/html")
        index = DASHBOARD_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index), media_type="text/html")
        return {"message": "AgentFramework API", "docs": "/docs", "dashboard_path": str(DASHBOARD_DIR)}

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        home = DASHBOARD_DIR / "home.html"
        if home.exists():
            return FileResponse(str(home), media_type="text/html")
        index = DASHBOARD_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index), media_type="text/html")
        return {"error": "Dashboard not found", "expected_path": str(DASHBOARD_DIR)}

    @app.get("/dashboard/develop", include_in_schema=False)
    async def develop_dashboard():
        page = DASHBOARD_DIR / "index.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "Develop dashboard not found"}

    @app.get("/dashboard/pipelines", include_in_schema=False)
    async def pipelines_dashboard():
        page = DASHBOARD_DIR / "pipelines.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "Pipelines dashboard not found"}

    @app.get("/dashboard/deploy-requests", include_in_schema=False)
    async def deploy_requests_dashboard():
        page = DASHBOARD_DIR / "deploy-requests.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "Deploy Requests dashboard not found"}

    @app.get("/dashboard/settings/agents", include_in_schema=False)
    async def settings_agents_dashboard():
        page = DASHBOARD_DIR / "settings-agents.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "Settings page not found"}

    @app.get("/dashboard/settings/deploy", include_in_schema=False)
    async def settings_deploy_dashboard():
        page = DASHBOARD_DIR / "settings-deploy.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "Settings page not found"}

    @app.get("/dashboard/knowledge", include_in_schema=False)
    async def knowledge_dashboard():
        page = DASHBOARD_DIR / "knowledge.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "Knowledge dashboard not found", "expected_path": str(page)}

    @app.get("/dashboard/review", include_in_schema=False)
    async def review_dashboard():
        page = DASHBOARD_DIR / "review.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "Review dashboard not found", "expected_path": str(page)}

    @app.get("/dashboard/rtk", include_in_schema=False)
    async def rtk_dashboard():
        page = DASHBOARD_DIR / "rtk.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "RTK dashboard not found", "expected_path": str(page)}

    @app.get("/dashboard/qa", include_in_schema=False)
    async def qa_dashboard():
        page = DASHBOARD_DIR / "qa.html"
        if page.exists():
            return FileResponse(str(page), media_type="text/html")
        return {"error": "QA dashboard not found", "expected_path": str(page)}

    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "env": settings.app_env,
            "dashboard": str(DASHBOARD_DIR),
            "dashboard_exists": DASHBOARD_DIR.exists(),
            "project_dotnet_version": settings.project_dotnet_version,
            "tracing": tracing_status(),
        }

    return app


app = create_app()
