#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OAuth Token Handler
Handles encrypted storage and retrieval of OAuth tokens
"""

import os
import json
import base64
import hashlib
import logging
import time
from typing import Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)


class OAuthTokenHandler:
    """
    Handles OAuth token storage with simple encryption
    Stores tokens in ~/.config/jackify/nexus-oauth.json
    """

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize token handler

        Args:
            config_dir: Optional custom config directory (defaults to ~/.config/jackify)
        """
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path.home() / ".config" / "jackify"

        self.token_file = self.config_dir / "nexus-oauth.json"

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Generate encryption key based on machine-specific data
        self._encryption_key = self._generate_encryption_key()

    def _generate_encryption_key(self) -> bytes:
        """
        Generate encryption key based on machine-specific data using Fernet

        Uses hostname + username + machine ID as key material, similar to DPAPI approach.
        This provides proper symmetric encryption while remaining machine-specific.

        Returns:
            Fernet-compatible 32-byte encryption key
        """
        import socket
        import getpass

        try:
            hostname = socket.gethostname()
            username = getpass.getuser()

            # Try to get machine ID for additional entropy
            machine_id = None
            try:
                # Linux machine-id
                with open('/etc/machine-id', 'r') as f:
                    machine_id = f.read().strip()
            except (OSError, IOError):
                try:
                    # Alternative locations
                    with open('/var/lib/dbus/machine-id', 'r') as f:
                        machine_id = f.read().strip()
                except (OSError, IOError):
                    pass

            # Combine multiple sources of machine-specific data
            if machine_id:
                key_material = f"{hostname}:{username}:{machine_id}:jackify"
            else:
                key_material = f"{hostname}:{username}:jackify"

        except Exception as e:
            logger.warning(f"Failed to get machine info for encryption: {e}")
            key_material = "jackify:default:key"

        # Generate 32-byte key using SHA256 for Fernet
        # Fernet requires base64-encoded 32-byte key
        key_bytes = hashlib.sha256(key_material.encode('utf-8')).digest()
        return base64.urlsafe_b64encode(key_bytes)

    def _encrypt_data(self, data: str) -> str:
        """
        Encrypt data using AES-GCM (authenticated encryption)

        Uses pycryptodome for cross-platform compatibility.
        AES-GCM provides authenticated encryption similar to Fernet.

        Args:
            data: Plain text data

        Returns:
            Encrypted data as base64 string (nonce:ciphertext:tag format)
        """
        try:
            from Crypto.Cipher import AES
            from Crypto.Random import get_random_bytes

            # Derive 32-byte AES key from encryption_key (which is base64-encoded)
            key = base64.urlsafe_b64decode(self._encryption_key)

            # Generate random nonce (12 bytes for GCM)
            nonce = get_random_bytes(12)

            # Create AES-GCM cipher
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

            # Encrypt and get authentication tag
            data_bytes = data.encode('utf-8')
            ciphertext, tag = cipher.encrypt_and_digest(data_bytes)

            # Combine nonce:ciphertext:tag and base64 encode
            combined = nonce + ciphertext + tag
            return base64.b64encode(combined).decode('utf-8')

        except ImportError:
            logger.error("pycryptodome package not available for token encryption")
            return ""
        except Exception as e:
            logger.error(f"Failed to encrypt data: {e}")
            return ""

    def _decrypt_data(self, encrypted_data: str) -> Optional[str]:
        """
        Decrypt data using AES-GCM (authenticated encryption)

        Args:
            encrypted_data: Encrypted data string (base64-encoded nonce:ciphertext:tag)

        Returns:
            Decrypted plain text or None on failure
        """
        try:
            from Crypto.Cipher import AES
            
            # Check if MODE_GCM is available (pycryptodome has it, old pycrypto doesn't)
            if not hasattr(AES, 'MODE_GCM'):
                logger.error("pycryptodome required for token decryption (pycrypto doesn't support MODE_GCM)")
                return None

            # Derive 32-byte AES key from encryption_key
            key = base64.urlsafe_b64decode(self._encryption_key)

            # Decode base64 and split nonce:ciphertext:tag
            combined = base64.b64decode(encrypted_data.encode('utf-8'))
            nonce = combined[:12]
            tag = combined[-16:]
            ciphertext = combined[12:-16]

            # Create AES-GCM cipher
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

            # Decrypt and verify authentication tag
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)

            return plaintext.decode('utf-8')

        except ImportError:
            logger.error("pycryptodome package not available for token decryption")
            return None
        except AttributeError:
            logger.error("pycryptodome required for token decryption (pycrypto doesn't support MODE_GCM)")
            return None
        except Exception as e:
            logger.error(f"Failed to decrypt data: {e}")
            return None

    def save_token(self, token_data: Dict) -> bool:
        """
        Save OAuth token to encrypted file with proper permissions

        Args:
            token_data: Token data dict from OAuth response

        Returns:
            True if saved successfully
        """
        try:
            # Add timestamp for tracking
            token_data['_saved_at'] = int(time.time())

            # Convert to JSON
            json_data = json.dumps(token_data, indent=2)

            # Encrypt using Fernet
            encrypted = self._encrypt_data(json_data)

            if not encrypted:
                logger.error("Encryption failed, cannot save token")
                return False

            # Save to file with restricted permissions
            # Write to temp file first, then move (atomic operation)
            import tempfile
            fd, temp_path = tempfile.mkstemp(dir=self.config_dir, prefix='.oauth_tmp_')

            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump({'encrypted_data': encrypted}, f, indent=2)

                # Set restrictive permissions (owner read/write only)
                os.chmod(temp_path, 0o600)

                # Atomic move
                os.replace(temp_path, self.token_file)

                logger.info(f"Saved encrypted OAuth token to {self.token_file}")
                return True

            except Exception as e:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except (OSError, IOError):
                    pass
                raise e

        except Exception as e:
            logger.error(f"Failed to save OAuth token: {e}")
            return False

    def load_token(self) -> Optional[Dict]:
        """
        Load OAuth token from encrypted file

        Returns:
            Token data dict or None if not found or invalid
        """
        if not self.token_file.exists():
            logger.debug("No OAuth token file found")
            return None

        try:
            # Load encrypted data
            with open(self.token_file, 'r') as f:
                data = json.load(f)

            encrypted = data.get('encrypted_data')
            if not encrypted:
                logger.error("Token file missing encrypted_data field")
                return None

            # Decrypt
            decrypted = self._decrypt_data(encrypted)
            if not decrypted:
                logger.error("Failed to decrypt token data")
                return None

            # Parse JSON
            token_data = json.loads(decrypted)

            logger.debug("Successfully loaded OAuth token")
            return token_data

        except json.JSONDecodeError as e:
            logger.error(f"Token file contains invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load OAuth token: {e}")
            return None

    def delete_token(self) -> bool:
        """
        Delete OAuth token file

        Returns:
            True if deleted successfully
        """
        try:
            if self.token_file.exists():
                self.token_file.unlink()
                logger.info("Deleted OAuth token file")
                return True
            else:
                logger.debug("No OAuth token file to delete")
                return False

        except Exception as e:
            logger.error(f"Failed to delete OAuth token: {e}")
            return False

    def has_token(self) -> bool:
        """
        Check if OAuth token file exists

        Returns:
            True if token file exists
        """
        return self.token_file.exists()

    def is_token_expired(self, token_data: Optional[Dict] = None, buffer_minutes: int = 5) -> bool:
        """
        Check if token is expired or close to expiring

        Args:
            token_data: Optional token data dict (loads from file if not provided)
            buffer_minutes: Minutes before expiry to consider token expired (default 5)

        Returns:
            True if token is expired or will expire within buffer_minutes
        """
        if token_data is None:
            token_data = self.load_token()

        if not token_data:
            return True

        # Extract OAuth data if nested
        oauth_data = token_data.get('oauth', token_data)

        # Get expiry information
        expires_in = oauth_data.get('expires_in')
        saved_at = token_data.get('_saved_at')

        if not expires_in or not saved_at:
            logger.debug("Token missing expiry information, assuming valid")
            return False  # Assume token is valid if no expiry info

        # Calculate expiry time
        expires_at = saved_at + expires_in
        buffer_seconds = buffer_minutes * 60
        now = int(time.time())

        # Check if expired or within buffer
        is_expired = (expires_at - buffer_seconds) < now

        if is_expired:
            remaining = expires_at - now
            if remaining < 0:
                logger.debug(f"Token expired {-remaining} seconds ago")
            else:
                logger.debug(f"Token expires in {remaining} seconds (within buffer)")

        return is_expired

    def get_access_token(self) -> Optional[str]:
        """
        Get access token from storage

        Returns:
            Access token string or None if not found or expired
        """
        token_data = self.load_token()

        if not token_data:
            return None

        # Check if expired
        if self.is_token_expired(token_data):
            logger.debug("Stored token is expired")
            return None

        # Extract access token from OAuth structure
        oauth_data = token_data.get('oauth', token_data)
        access_token = oauth_data.get('access_token')

        if not access_token:
            logger.error("Token data missing access_token field")
            return None

        return access_token

    def get_refresh_token(self) -> Optional[str]:
        """
        Get refresh token from storage

        Returns:
            Refresh token string or None if not found
        """
        token_data = self.load_token()

        if not token_data:
            return None

        # Extract refresh token from OAuth structure
        oauth_data = token_data.get('oauth', token_data)
        refresh_token = oauth_data.get('refresh_token')

        return refresh_token

    def get_token_info(self) -> Dict:
        """
        Get diagnostic information about current token

        Returns:
            Dict with token status information
        """
        token_data = self.load_token()

        if not token_data:
            return {
                'has_token': False,
                'error': 'No token file found'
            }

        oauth_data = token_data.get('oauth', token_data)
        expires_in = oauth_data.get('expires_in')
        saved_at = token_data.get('_saved_at')

        # Check if refresh token is likely expired (30 days since last auth)
        # Nexus doesn't provide refresh token expiry, so we estimate conservatively
        REFRESH_TOKEN_LIFETIME_DAYS = 30
        now = int(time.time())
        refresh_token_age_days = (now - saved_at) / 86400 if saved_at else 0
        refresh_token_likely_expired = refresh_token_age_days > REFRESH_TOKEN_LIFETIME_DAYS

        if expires_in and saved_at:
            expires_at = saved_at + expires_in
            remaining_seconds = expires_at - now

            return {
                'has_token': True,
                'has_refresh_token': bool(oauth_data.get('refresh_token')),
                'expires_in_seconds': remaining_seconds,
                'expires_in_minutes': remaining_seconds / 60,
                'expires_in_hours': remaining_seconds / 3600,
                'is_expired': remaining_seconds < 0,
                'expires_soon_5min': remaining_seconds < 300,
                'expires_soon_15min': remaining_seconds < 900,
                'saved_at': saved_at,
                'expires_at': expires_at,
                'refresh_token_age_days': refresh_token_age_days,
                'refresh_token_likely_expired': refresh_token_likely_expired,
            }
        else:
            return {
                'has_token': True,
                'has_refresh_token': bool(oauth_data.get('refresh_token')),
                'refresh_token_age_days': refresh_token_age_days,
                'refresh_token_likely_expired': refresh_token_likely_expired,
                'error': 'Token missing expiry information'
            }
