"""
User API Key Management with Encryption

Provides secure storage and retrieval of user API keys (Cursor SDK, Atlassian tokens)
with AES-256 encryption at rest using cryptography.fernet.
"""

import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class KeyManager:
    """Manages encrypted user API keys with file-based storage."""

    def __init__(self, keys_dir: str = "data/user_keys"):
        """
        Initialize KeyManager with encryption.

        Args:
            keys_dir: Directory to store encrypted key files
        """
        self.keys_dir = Path(keys_dir)
        self.keys_dir.mkdir(parents=True, exist_ok=True)

        # Get master encryption key from environment
        encryption_key = os.environ.get("REGX_ENCRYPTION_KEY")
        
        if not encryption_key:
            # Check if we're in development
            is_dev = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes", "on")
            is_dev = is_dev or os.environ.get("FLASK_ENV", "").lower() in ("development", "dev")
            
            if is_dev:
                logger.warning(
                    "REGX_ENCRYPTION_KEY not set. Generating temporary key for development. "
                    "User keys will not persist across restarts. Set REGX_ENCRYPTION_KEY in production."
                )
                encryption_key = Fernet.generate_key().decode()
            else:
                raise ValueError(
                    "REGX_ENCRYPTION_KEY environment variable is required in production. "
                    "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
        
        # Ensure key is bytes
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()
        
        self.cipher = Fernet(encryption_key)
        logger.info(f"KeyManager initialized with storage at {self.keys_dir}")

    def _get_user_file_path(self, username: str) -> Path:
        """Get the encrypted file path for a user."""
        # Sanitize username for filename
        safe_username = "".join(c for c in username if c.isalnum() or c in "._-")
        return self.keys_dir / f"{safe_username}_keys.enc"

    def save_keys(self, username: str, keys_dict: Dict[str, str]) -> bool:
        """
        Encrypt and save user API keys.

        Args:
            username: User identifier
            keys_dict: Dictionary of API keys to store

        Returns:
            True if successful, False otherwise
        """
        if not username:
            raise ValueError("Username cannot be empty")

        try:
            # Add metadata
            data = {
                "keys": keys_dict,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            # Check if file exists to preserve created_at
            user_file = self._get_user_file_path(username)
            if user_file.exists():
                try:
                    existing = self.get_keys(username, include_metadata=True)
                    data["created_at"] = existing.get("created_at")
                except Exception:
                    pass

            if "created_at" not in data:
                data["created_at"] = data["updated_at"]

            # Encrypt and save
            json_str = json.dumps(data, indent=2)
            encrypted = self.cipher.encrypt(json_str.encode())
            
            user_file.write_bytes(encrypted)
            logger.info(f"Saved encrypted keys for user: {username}")
            return True

        except Exception as e:
            logger.error(f"Failed to save keys for {username}: {e}")
            return False

    def get_keys(self, username: str, include_metadata: bool = False) -> Optional[Dict[str, str]]:
        """
        Decrypt and retrieve user API keys.

        Args:
            username: User identifier
            include_metadata: If True, return full data including timestamps

        Returns:
            Dictionary of API keys, or None if not found
        """
        if not username:
            return None

        user_file = self._get_user_file_path(username)
        
        if not user_file.exists():
            logger.debug(f"No keys found for user: {username}")
            return None

        try:
            encrypted = user_file.read_bytes()
            decrypted = self.cipher.decrypt(encrypted)
            data = json.loads(decrypted.decode())
            
            logger.info(f"Retrieved keys for user: {username}")
            
            if include_metadata:
                return data
            else:
                return data.get("keys", {})

        except InvalidToken:
            logger.error(f"Invalid encryption token for user: {username}. Keys may be corrupted.")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve keys for {username}: {e}")
            return None

    def delete_keys(self, username: str) -> bool:
        """
        Delete user's encrypted key file.

        Args:
            username: User identifier

        Returns:
            True if deleted, False if not found or error
        """
        if not username:
            return False

        user_file = self._get_user_file_path(username)
        
        if not user_file.exists():
            return False

        try:
            user_file.unlink()
            logger.info(f"Deleted keys for user: {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete keys for {username}: {e}")
            return False

    def has_keys(self, username: str) -> bool:
        """Check if user has keys stored."""
        return self._get_user_file_path(username).exists()

    def mask_key(self, key: str, prefix_len: int = 8, suffix_len: int = 4) -> str:
        """
        Mask an API key for display.

        Args:
            key: The API key to mask
            prefix_len: Number of characters to show at start
            suffix_len: Number of characters to show at end

        Returns:
            Masked key string like "crsr_abcd****...****xyz1"
        """
        if not key:
            return ""
        
        if len(key) <= prefix_len + suffix_len:
            return key  # Too short to mask

        prefix = key[:prefix_len]
        suffix = key[-suffix_len:]
        return f"{prefix}****...****{suffix}"

    def mask_keys_dict(self, keys_dict: Dict[str, str]) -> Dict[str, str]:
        """
        Mask all keys in a dictionary for safe display.

        Args:
            keys_dict: Dictionary of keys

        Returns:
            Dictionary with masked values
        """
        if not keys_dict:
            return {}

        masked = {}
        for key, value in keys_dict.items():
            if value:
                masked[key] = self.mask_key(value)
            else:
                masked[key] = ""
        
        return masked
