"""
Unit tests for encryption service
"""

import pytest
from app.core.encryption import encryption_service


@pytest.mark.unit
def test_encrypt_decrypt_aadhaar():
    """Test Aadhaar encryption and decryption roundtrip"""
    original = "123456789012"
    
    # Encrypt
    encrypted = encryption_service.encrypt_aadhaar(original)
    assert encrypted != original
    assert len(encrypted) > 0
    
    # Decrypt
    decrypted = encryption_service.decrypt_aadhaar(encrypted)
    assert decrypted == original


@pytest.mark.unit
def test_encrypt_decrypt_pan():
    """Test PAN encryption and decryption roundtrip"""
    original = "ABCDE1234F"
    
    # Encrypt
    encrypted = encryption_service.encrypt_pan(original)
    assert encrypted != original
    assert len(encrypted) > 0
    
    # Decrypt
    decrypted = encryption_service.decrypt_pan(encrypted)
    assert decrypted == original


@pytest.mark.unit
def test_hash_aadhaar_consistency():
    """Test that hashing the same Aadhaar produces the same hash"""
    aadhaar1 = "1234 5678 9012"
    aadhaar2 = "123456789012"  # Same without spaces
    
    hash1 = encryption_service.hash_aadhaar(aadhaar1)
    hash2 = encryption_service.hash_aadhaar(aadhaar2)
    
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 produces 64 hex characters


@pytest.mark.unit
def test_hash_aadhaar_different():
    """Test that different Aadhaar numbers produce different hashes"""
    aadhaar1 = "123456789012"
    aadhaar2 = "123456789013"
    
    hash1 = encryption_service.hash_aadhaar(aadhaar1)
    hash2 = encryption_service.hash_aadhaar(aadhaar2)
    
    assert hash1 != hash2


@pytest.mark.unit
def test_mask_aadhaar():
    """Test Aadhaar masking"""
    aadhaar = "123456789012"
    masked = encryption_service.mask_aadhaar(aadhaar)
    
    assert masked == "XXXX XXXX 9012"


@pytest.mark.unit
def test_mask_aadhaar_with_spaces():
    """Test Aadhaar masking with spaces"""
    aadhaar = "1234 5678 9012"
    masked = encryption_service.mask_aadhaar(aadhaar)
    
    assert masked == "XXXX XXXX 9012"


@pytest.mark.unit
def test_mask_pan():
    """Test PAN masking"""
    pan = "ABCDE1234F"
    masked = encryption_service.mask_pan(pan)
    
    assert masked == "ABCXX1234F"
