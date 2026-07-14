"""
BankAI — Production-Grade KYC Backend
FastAPI server with Firebase Firestore, encryption, and JWT authentication
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from datetime import datetime
import uvicorn
import os

from app.core.config import settings, llm_settings
from app.core.logging import setup_logging, get_logger, set_correlation_id
from app.api.v1 import kyc, auth, forms, submissions, conversation, admin

# Setup logging
setup_logging()
logger = get_logger()

# Rate limiter — keyed by client IP address
from app.core.rate_limit import limiter

app = FastAPI(
    title=settings.APP_NAME,
    description="Production-grade KYC verification backend with encryption and authentication",
    version=settings.APP_VERSION,
)

# Register rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Middleware for correlation ID (request tracing)
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add correlation ID to each request for tracing"""
    correlation_id = request.headers.get("X-Correlation-ID")
    # Always generate a correlation ID — use client-supplied one if present
    correlation_id = set_correlation_id(correlation_id)

    response = await call_next(request)

    # Always echo correlation ID back so clients can trace server logs
    response.headers["X-Correlation-ID"] = correlation_id

    return response


# CORS — allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# API routes
app.include_router(kyc.router, prefix="/api/v1/kyc", tags=["KYC"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(forms.router, prefix="/api/v1/forms", tags=["Forms"])
app.include_router(submissions.router, prefix="/api/v1/submissions", tags=["Submissions"])
app.include_router(conversation.router, prefix="/api/v1/conversation", tags=["Conversation"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])



@app.get("/api/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.on_event("startup")
async def startup_event():
    """Startup event — init Firestore, seed defaults, init checkpointer"""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Initialise Firebase/Firestore connection
    from app.database import init_db
    init_db()
    logger.info("Firestore connection initialised")

    # Seed default banks, forms, and admin user
    from app.core.seed import seed_defaults
    seed_defaults()

    # Initialise conversation checkpointer (MemorySaver)
    from app.core.checkpointer import init_checkpointer
    init_checkpointer()

    # Recompile the agent graph with the checkpointer
    if llm_settings.is_configured:
        try:
            from app.services.ai_agent_service import recompile_graph
            recompile_graph()
            logger.info("Agent graph recompiled with checkpointer")
        except Exception as exc:
            logger.warning(f"Could not recompile agent graph: {exc}")

    logger.info("Application started successfully")
    if llm_settings.is_configured:
        logger.info(
            f"LLM enabled: provider={llm_settings.LLM_PROVIDER}, "
            f"model={llm_settings.LLM_MODEL}"
        )
    else:
        logger.info("LLM not configured — using keyword-based conversation agent")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event — release checkpointer"""
    from app.core.checkpointer import shutdown_checkpointer
    shutdown_checkpointer()
    logger.info("Application shutting down")


# Serve frontend static files from project root (MUST be last — catch-all)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
