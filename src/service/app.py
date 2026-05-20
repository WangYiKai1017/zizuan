"""FastAPI application factory for the Agent Service."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize services on startup."""
    # Initialize LLM service singleton on startup
    from dotenv import load_dotenv
    load_dotenv()
    
    from src.services.llm_service import get_llm_service
    get_llm_service()  # Trigger singleton initialization
    
    yield
    # Cleanup on shutdown (if needed)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="老人自传写作 Agent 服务",
        description="将采访、知识库整理、传记大纲、传记写作四个Agent封装为HTTP/SSE服务",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to frontend domain
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register routers
    from src.service.routes.interview import router as interview_router
    from src.service.routes.kb_organizer import router as kb_organizer_router
    from src.service.routes.biography_outline import router as outline_router
    from src.service.routes.biography_writing import router as writing_router
    from src.service.routes.files import router as files_router
    
    app.include_router(interview_router, prefix="/api")
    app.include_router(kb_organizer_router, prefix="/api")
    app.include_router(outline_router, prefix="/api")
    app.include_router(writing_router, prefix="/api")
    app.include_router(files_router, prefix="/api")
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "ok", "service": "agent-service"}
    
    return app
