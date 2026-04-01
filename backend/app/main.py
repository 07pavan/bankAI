"""
BankAI — Production-Grade KYC Backend
FastAPI server with PostgreSQL, encryption, and JWT authentication
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from datetime import datetime
import uvicorn
import os

from app.core.config import settings
from app.core.logging import setup_logging, get_logger, set_correlation_id
from app.api.v1 import kyc, auth, forms, submissions, conversation, admin

# Setup logging
setup_logging()
logger = get_logger()

app = FastAPI(
    title=settings.APP_NAME,
    description="Production-grade KYC verification backend with encryption and authentication",
    version=settings.APP_VERSION,
)


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
    """Startup event - verify database connection and seed defaults"""
    from app.database import SessionLocal
    from app.core.seed import seed_defaults
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info("Database connection configured")
    db = SessionLocal()
    try:
        seed_defaults(db)
    finally:
        db.close()
    logger.info("Application started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event"""
    logger.info("Application shutting down")


# Serve frontend static files from project root (MUST be last — catch-all)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
