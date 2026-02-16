"""
BankAI — KYC Backend
FastAPI server for KYC document submission and storage
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import datetime
import uvicorn
import os

from database import engine, get_db
from models import Base
from routers import kyc

# Create DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="BankAI KYC API",
    description="Camera-based KYC verification backend",
    version="1.0.0",
)

# CORS — allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(kyc.router, prefix="/api/kyc", tags=["KYC"])


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "BankAI KYC",
        "timestamp": datetime.utcnow().isoformat(),
    }


# Serve frontend static files from parent directory (MUST be last — catch-all)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
