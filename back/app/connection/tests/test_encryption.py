"""Tests for the encryption service."""

import base64

import pytest
from unittest.mock import patch, MagicMock

from core.util import EncryptionService, encrypt_value, decrypt_value, get_encryption_service


class TestEncryptionService:
    """Tests for the encryption service."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before each test."""
        EncryptionService._instance = None
        EncryptionService._fernet = None
        yield
        EncryptionService._instance = None
        EncryptionService._fernet = None

    @patch("core.util.encryption.settings")
    def test_encrypt_decrypt(self, mock_settings):
        """Test basic encryption and decryption."""
        # Arrange
        mock_settings.ENCRYPTION_MASTER_KEY = "test_secret_key_for_encryption_32bytes!"

        service = EncryptionService()
        original_value = "my_secret_password_123"

        # Act
        encrypted = service.encrypt(original_value)
        decrypted = service.decrypt(encrypted)

        # Assert
        assert encrypted != original_value
        assert decrypted == original_value
        assert service.is_encrypted(encrypted) is True
        assert service.is_encrypted(original_value) is False

    @patch("core.util.encryption.settings")
    def test_encrypt_empty_value(self, mock_settings):
        """Test encryption of an empty value."""
        mock_settings.ENCRYPTION_MASTER_KEY = "test_secret_key_for_encryption_32bytes!"

        service = EncryptionService()

        assert service.encrypt("") == ""
        assert service.encrypt(None) is None

    @patch("core.util.encryption.settings")
    def test_decrypt_empty_value(self, mock_settings):
        """Test decryption of an empty value."""
        mock_settings.ENCRYPTION_MASTER_KEY = "test_secret_key_for_encryption_32bytes!"

        service = EncryptionService()

        assert service.decrypt("") == ""
        assert service.decrypt(None) is None

    @patch("core.util.encryption.settings")
    def test_is_encrypted_with_plain_text(self, mock_settings):
        """Test detection of unencrypted text."""
        mock_settings.ENCRYPTION_MASTER_KEY = "test_secret_key_for_encryption_32bytes!"

        service = EncryptionService()

        assert service.is_encrypted("plain_text") is False
        assert service.is_encrypted("password123") is False
        assert service.is_encrypted("") is False
        opaque_token = base64.urlsafe_b64encode(b"x" * 96).decode()
        assert service.is_encrypted(opaque_token) is False

    @patch("core.util.encryption.settings")
    def test_helper_functions(self, mock_settings):
        """Test the encrypt_value and decrypt_value helpers."""
        mock_settings.ENCRYPTION_MASTER_KEY = "test_secret_key_for_encryption_32bytes!"

        original = "super_secret"
        encrypted = encrypt_value(original)
        decrypted = decrypt_value(encrypted)

        assert encrypted != original
        assert decrypted == original

    @patch("core.util.encryption.settings")
    def test_missing_master_key(self, mock_settings):
        """Test the error raised when the master key is undefined."""
        mock_settings.ENCRYPTION_MASTER_KEY = ""

        with pytest.raises(ValueError, match="ENCRYPTION_MASTER_KEY"):
            EncryptionService()

    @patch("core.util.encryption.settings")
    def test_different_values_produce_different_ciphertexts(self, mock_settings):
        """Test that distinct values produce distinct ciphertexts."""
        mock_settings.ENCRYPTION_MASTER_KEY = "test_secret_key_for_encryption_32bytes!"

        service = EncryptionService()

        encrypted1 = service.encrypt("password1")
        encrypted2 = service.encrypt("password2")

        assert encrypted1 != encrypted2

    @patch("core.util.encryption.settings")
    def test_same_value_produces_different_ciphertexts(self, mock_settings):
        """Test that Fernet encrypts one value to distinct ciphertexts."""
        mock_settings.ENCRYPTION_MASTER_KEY = "test_secret_key_for_encryption_32bytes!"

        service = EncryptionService()

        encrypted1 = service.encrypt("same_password")
        encrypted2 = service.encrypt("same_password")

        # Fernet uses a random IV, so the ciphertexts differ.
        assert encrypted1 != encrypted2
        # Both still decrypt to the same value.
        assert service.decrypt(encrypted1) == service.decrypt(encrypted2)
