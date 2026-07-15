"""
Core configuration management for BankAI
Loads environment variables and provides centralized settings
"""

from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Firebase Configuration
    FIREBASE_CREDENTIALS_JSON: Optional[str] = None
    FIREBASE_CREDENTIALS_PATH: Optional[str] = None
    FIREBASE_PROJECT_ID: Optional[str] = None
    
    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    # Encryption
    ENCRYPTION_KEY: str
    
    # Deepgram
    DEEPGRAM_API_KEY: Optional[str] = None
    
    # OCR.space
    OCR_SPACE_API_KEY: str = "helloworld"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"
    LOG_MAX_BYTES: int = 10485760  # 10MB
    LOG_BACKUP_COUNT: int = 5
    
    # CORS
    CORS_ORIGINS: str = "http://localhost:8000"
    
    # Application
    APP_NAME: str = "BankAI KYC API"
    APP_VERSION: str = "2.0.0"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


class LLMSettings(BaseSettings):
    """LLM / LangGraph configuration — all fields optional for backward compat"""

    LLM_PROVIDER: str = "xai"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "grok-3-mini"
    LLM_TEMPERATURE: float = 0.3
    @property
    def is_configured(self) -> bool:
        """True when an API key is present, i.e. LLM features are enabled"""
        return bool(self.LLM_API_KEY)

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


# Global settings instances
settings = Settings()
llm_settings = LLMSettings()
