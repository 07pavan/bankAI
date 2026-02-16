"""
SQLAlchemy models for KYC data
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Enum
from sqlalchemy.sql import func
from database import Base
import enum


class KYCStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class KYCSubmission(Base):
    __tablename__ = "kyc_submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    aadhaar_number = Column(String(14), nullable=False)          # "XXXX XXXX XXXX"
    pan_number = Column(String(10), nullable=False)              # "ABCDE1234F"
    selfie_path = Column(String(255), nullable=True)             # file path to saved selfie
    status = Column(String(20), default=KYCStatus.PENDING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<KYCSubmission(id={self.id}, aadhaar=***{self.aadhaar_number[-4:]}, status={self.status})>"
