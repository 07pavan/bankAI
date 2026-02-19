"""
Encryption utilities for sensitive data (Aadhaar, PAN)
Uses Fernet symmetric encryption from cryptography library
"""

from cryptography.fernet import Fernet
from app.core.config import settings
import hashlib
import base64


class EncryptionService:
    """Service for encrypting/decrypting sensitive data"""
    
    def __init__(self):
        # Initialize Fernet cipher with key from settings
        key = settings.ENCRYPTION_KEY.encode()
        self.cipher = Fernet(key)
    
    def encrypt_aadhaar(self, aadhaar: str) -> str:
        """
        Encrypt Aadhaar number
        Returns base64-encoded encrypted string
        """
        # Remove spaces and encrypt
        cleaned = aadhaar.replace(" ", "")
        encrypted = self.cipher.encrypt(cleaned.encode())
        return base64.b64encode(encrypted).decode()
    
    def decrypt_aadhaar(self, encrypted: str) -> str:
        """
        Decrypt Aadhaar number
        Returns original 12-digit number
        """
        encrypted_bytes = base64.b64decode(encrypted.encode())
        decrypted = self.cipher.decrypt(encrypted_bytes)
        return decrypted.decode()
    
    def encrypt_pan(self, pan: str) -> str:
        """
        Encrypt PAN number
        Returns base64-encoded encrypted string
        """
        encrypted = self.cipher.encrypt(pan.upper().encode())
        return base64.b64encode(encrypted).decode()
    
    def decrypt_pan(self, encrypted: str) -> str:
        """
        Decrypt PAN number
        Returns original PAN
        """
        encrypted_bytes = base64.b64decode(encrypted.encode())
        decrypted = self.cipher.decrypt(encrypted_bytes)
        return decrypted.decode()
    
    def hash_aadhaar(self, aadhaar: str) -> str:
        """
        Create one-way hash of Aadhaar for duplicate detection
        Uses SHA-256 for consistent hashing
        """
        cleaned = aadhaar.replace(" ", "")
        return hashlib.sha256(cleaned.encode()).hexdigest()
    
    def mask_aadhaar(self, aadhaar: str) -> str:
        """
        Mask Aadhaar for display: XXXX XXXX 1234
        """
        cleaned = aadhaar.replace(" ", "")
        if len(cleaned) != 12:
            return "XXXX XXXX XXXX"
        return f"XXXX XXXX {cleaned[-4:]}"
    
    def mask_pan(self, pan: str) -> str:
        """
        Mask PAN for display: ABCXX1234X
        """
        if len(pan) != 10:
            return "XXXXX1234X"
        return f"{pan[:3]}XX{pan[5:9]}{pan[-1]}"


# Global encryption service instance
encryption_service = EncryptionService()
