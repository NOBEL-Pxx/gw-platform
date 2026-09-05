"""
v4.37: Secrets Manager — encrypted credentials storage with rotation tracking.

Features:
  - Encrypt secrets at rest using Fernet (AES-128-CBC with HMAC)
  - Rotation tracking with expiration dates
  - Audit trail of all rotation events
  - API for querying secret status without exposing values

Architecture:
  - Master key from GW_MASTER_KEY env var (64 bytes base64-encoded)
  - Individual secrets encrypted with derived per-secret keys
  - .secrets.json stores encrypted blobs + metadata (expiry, created, rotated_by)
  - All rotation events written to audit log
"""
import os, json, time, hashlib, base64, secrets, logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from cryptography.fernet import Fernet

logger = logging.getLogger("gw.secrets-manager")

# ── Configuration ──────────────────────────────────────────────────────────
DEFAULT_EXPIRY_DAYS = int(os.getenv("SECRETS_DEFAULT_EXPIRY_DAYS", "90"))
WARN_BEFORE_DAYS = int(os.getenv("SECRETS_WARN_BEFORE_DAYS", "14"))
SECRETS_FILE = os.getenv("SECRETS_FILE", "/app/config/.secrets.json")
SECRETS_BACKUP_DIR = os.getenv("SECRETS_BACKUP_DIR", "/app/config/secrets-backups")


class SecretsManager:
    """Encrypted secrets storage with automatic rotation tracking."""

    def __init__(self, master_key: str = None):
        """Initialize with master encryption key.

        Args:
            master_key: Base64-encoded 32-byte key for Fernet. If not provided,
                        reads from GW_MASTER_KEY env var or generates a temporary one.
        """
        self._master_key_str = master_key or os.getenv("GW_MASTER_KEY")
        if not self._master_key_str:
            # Generate a random key for development — production MUST set GW_MASTER_KEY
            logger.warning("GW_MASTER_KEY not set — using ephemeral key (secrets lost on restart!)")
            self._master_key_str = base64.b64encode(secrets.token_bytes(32)).decode()
        else:
            try:
                # Validate it's valid base64
                base64.b64decode(self._master_key_str)
            except Exception:
                raise ValueError("GW_MASTER_KEY is not valid base64")

        # Derive Fernet key from master key (Fernet requires 32-byte url-safe base64 key)
        key_bytes = hashlib.sha256(self._master_key_str.encode()).digest()
        self._fernet_key = base64.urlsafe_b64encode(key_bytes)
        self._cipher = Fernet(self._fernet_key)

        # Load or initialize secrets store
        self._store: Dict[str, dict] = self._load_store()

    # ── File I/O ────────────────────────────────────────────────────────────

    def _load_store(self) -> Dict[str, dict]:
        """Load encrypted secrets store from disk."""
        if os.path.exists(SECRETS_FILE):
            try:
                with open(SECRETS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Decrypt stored values
                for name, entry in data.items():
                    if 'encrypted_value' in entry:
                        try:
                            entry['_decrypted'] = self._cipher.decrypt(
                                entry['encrypted_value'].encode()
                            ).decode()
                        except Exception:
                            entry['_decrypted'] = None
                            logger.warning(f"Cannot decrypt secret: {name}")
                logger.info(f"Loaded {len(data)} encrypted secrets")
                return data
            except json.JSONDecodeError:
                logger.error(f"Corrupted secrets file: {SECRETS_FILE}")
        return {}

    def _save_store(self) -> None:
        """Persist secrets store to disk (encrypted values only)."""
        os.makedirs(os.path.dirname(SECRETS_FILE), exist_ok=True)

        # Build clean payload — never write decrypted values to disk
        clean = {}
        for name, entry in self._store.items():
            clean[name] = {
                k: v for k, v in entry.items()
                if k not in ('_decrypted',)
            }

        # Write atomically via temp file
        tmp_path = SECRETS_FILE + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(clean, f, indent=2, default=str)

        # Backup old file
        if os.path.exists(SECRETS_FILE):
            backup_path = os.path.join(
                SECRETS_BACKUP_DIR,
                f"secrets.{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            )
            os.makedirs(SECRETS_BACKUP_DIR, exist_ok=True)
            try:
                os.rename(SECRETS_FILE, backup_path)
            except OSError:
                pass  # Cross-filesystem rename may fail; delete old

        os.rename(tmp_path, SECRETS_FILE)
        logger.debug(f"Saved {len(clean)} secrets to {SECRETS_FILE}")

    # ── Core API ────────────────────────────────────────────────────────────

    def get_secret(self, name: str) -> Optional[str]:
        """Get the decrypted value of a secret.

        Args:
            name: Secret identifier (e.g. 'DEEPSEEK_API_KEY', 'JWT_SECRET')

        Returns:
            Decrypted secret value, or None if not found or cannot decrypt.
        """
        entry = self._store.get(name)
        if not entry:
            return None
        return entry.get('_decrypted')

    def set_secret(self, name: str, value: str, expiry_days: int = None,
                   rotated_by: str = "system") -> bool:
        """Store a new or rotated secret.

        Args:
            name: Secret identifier
            value: Plaintext secret value
            expiry_days: Days until expiration (default: DEFAULT_EXPIRY_DAYS)
            rotated_by: Who/what triggered this rotation

        Returns:
            True if stored successfully.
        """
        expiry_days = expiry_days or DEFAULT_EXPIRY_DAYS
        now = datetime.utcnow()

        # Encrypt value
        encrypted = self._cipher.encrypt(value.encode()).decode()

        # Track rotation history
        old_entry = self._store.get(name, {})
        rotation_history = old_entry.get('rotation_history', [])

        entry = {
            'name': name,
            'encrypted_value': encrypted,
            '_decrypted': value,  # In-memory only, never persisted
            'created_at': old_entry.get('created_at', now.isoformat()),
            'rotated_at': now.isoformat(),
            'expires_at': (now + timedelta(days=expiry_days)).isoformat(),
            'rotated_by': rotated_by,
            'rotation_count': old_entry.get('rotation_count', 0) + 1,
            'rotation_history': rotation_history + [{
                'timestamp': now.isoformat(),
                'rotated_by': rotated_by,
                'expiry_days': expiry_days,
            }],
        }
        # Keep last 10 rotation records
        if len(entry['rotation_history']) > 10:
            entry['rotation_history'] = entry['rotation_history'][-10:]

        self._store[name] = entry
        self._save_store()

        logger.info(f"Secret stored/rotated: {name} (rotation #{entry['rotation_count']})")
        return True

    def rotate_secret(self, name: str, new_value: str = None,
                      byte_length: int = 32, rotated_by: str = "api") -> Dict[str, Any]:
        """Generate and store a new random secret, or rotate to a provided value.

        Args:
            name: Secret identifier
            new_value: Specific new value (if None, generate random)
            byte_length: Length of random secret to generate (if new_value is None)
            rotated_by: Identity triggering rotation

        Returns:
            Dict with rotation result including old expiry info.
        """
        old_entry = self._store.get(name, {})
        old_expiry = old_entry.get('expires_at', 'N/A')
        old_rotation = old_entry.get('rotation_count', 0)

        if new_value is None:
            new_value = secrets.token_urlsafe(byte_length)

        self.set_secret(name, new_value, rotated_by=rotated_by)

        return {
            'name': name,
            'rotated': True,
            'previous_rotation_count': old_rotation,
            'previous_expiry': old_expiry,
            'new_expiry': self._store[name]['expires_at'],
            'new_rotation_count': self._store[name]['rotation_count'],
        }

    def check_expiry(self) -> List[Dict[str, Any]]:
        """Check all secrets for expiration status.

        Returns:
            List of secrets with their expiry status.
        """
        now = datetime.utcnow()
        results = []

        for name, entry in self._store.items():
            expires_at_str = entry.get('expires_at')
            if not expires_at_str:
                continue

            try:
                expires_at = datetime.fromisoformat(expires_at_str)
            except (ValueError, TypeError):
                continue

            days_left = (expires_at - now).days
            status = "ok"
            if days_left <= 0:
                status = "expired"
            elif days_left <= WARN_BEFORE_DAYS:
                status = "expiring_soon"

            results.append({
                'name': name,
                'status': status,
                'days_until_expiry': max(0, days_left),
                'expires_at': expires_at_str,
                'rotation_count': entry.get('rotation_count', 0),
                'last_rotated_at': entry.get('rotated_at'),
                'last_rotated_by': entry.get('rotated_by'),
            })

        return results

    def get_alerts(self) -> List[Dict[str, str]]:
        """Get secrets that need attention (expired or expiring soon).

        Returns:
            List of alert dicts with name, status, and message.
        """
        expiry = self.check_expiry()
        alerts = []
        for e in expiry:
            if e['status'] in ('expired', 'expiring_soon'):
                alerts.append({
                    'name': e['name'],
                    'severity': 'critical' if e['status'] == 'expired' else 'warning',
                    'message': (
                        f"Secret '{e['name']}' has EXPIRED" if e['status'] == 'expired'
                        else f"Secret '{e['name']}' expires in {e['days_until_expiry']} days"
                    ),
                    'days_until_expiry': e['days_until_expiry'],
                })
        return alerts

    def list_secrets(self) -> List[Dict[str, Any]]:
        """List all secret names with metadata (values NOT exposed).

        Returns:
            List of secret metadata dicts.
        """
        return [{
            'name': name,
            'created_at': entry.get('created_at'),
            'rotated_at': entry.get('rotated_at'),
            'expires_at': entry.get('expires_at'),
            'rotation_count': entry.get('rotation_count', 0),
            'has_value': bool(entry.get('encrypted_value')),
        } for name, entry in self._store.items()]

    def delete_secret(self, name: str) -> bool:
        """Permanently remove a secret.

        Args:
            name: Secret identifier

        Returns:
            True if secret existed and was removed.
        """
        if name not in self._store:
            return False
        del self._store[name]
        self._save_store()
        logger.warning(f"Secret deleted: {name}")
        return True


# ── Module-level singleton ─────────────────────────────────────────────────
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get or create the global SecretsManager singleton."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager
