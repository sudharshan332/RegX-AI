"""Per-user API key storage for RegX User Settings.

Keys are encrypted at rest (Fernet) and returned masked on GET.
Used for Cursor / Atlassian Jira / Confluence personal tokens.

Encryption uses a stable key file under data/ so tokens survive backend
restarts even when SECRET_KEY is randomly generated.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ALLOWED_KEY_NAMES = (
    "cursor_api_key",
    "atlassian_jira_token",
    "atlassian_confluence_token",
)

_LOCK = threading.Lock()
_FERNET = None


def _data_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(os.path.dirname(here), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _store_path() -> str:
    override = (os.environ.get("REGX_USER_KEYS_FILE") or "").strip()
    if override:
        parent = os.path.dirname(override)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return override
    return os.path.join(_data_dir(), "user_api_keys.json")


def _fernet_key_path() -> str:
    override = (os.environ.get("REGX_USER_KEYS_FERNET_FILE") or "").strip()
    if override:
        parent = os.path.dirname(override)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return override
    return os.path.join(_data_dir(), "user_api_keys.fernet")


def _fernet():
    """Stable Fernet cipher (persisted file, or env-derived)."""
    global _FERNET
    if _FERNET is not None:
        return _FERNET

    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography package is required for user API key encryption"
        ) from exc

    # 1) Explicit env secret (optional)
    env_secret = (
        os.environ.get("REGX_USER_KEYS_SECRET")
        or os.environ.get("SECRET_KEY")
        or os.environ.get("REGX_SECRET_KEY")
        or ""
    ).strip()

    key_path = _fernet_key_path()
    key_bytes = None

    # 2) Prefer persisted Fernet key so restarts don't invalidate stored tokens
    #    when Flask generates a random SECRET_KEY each boot.
    if os.path.isfile(key_path):
        try:
            with open(key_path, "rb") as fh:
                key_bytes = fh.read().strip()
        except Exception as exc:
            logger.warning("Could not read user-keys fernet file: %s", exc)

    if not key_bytes:
        if env_secret and env_secret != "regx-dev-user-keys-insecure":
            digest = hashlib.sha256(env_secret.encode("utf-8")).digest()
            key_bytes = base64.urlsafe_b64encode(digest)
        else:
            key_bytes = Fernet.generate_key()
        try:
            with open(key_path, "wb") as fh:
                fh.write(key_bytes)
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
            logger.info("Created stable user-keys encryption file at %s", key_path)
        except Exception as exc:
            logger.warning("Could not persist user-keys fernet file: %s", exc)

    _FERNET = Fernet(key_bytes)
    return _FERNET


def _load_raw() -> Dict[str, Any]:
    path = _store_path()
    if not os.path.isfile(path):
        return {"users": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"users": {}}
        if not isinstance(data.get("users"), dict):
            data["users"] = {}
        return data
    except Exception as exc:
        logger.error("Failed to load user API keys store: %s", exc)
        return {"users": {}}


def _save_raw(data: Dict[str, Any]) -> None:
    path = _store_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def mask_secret(value: str) -> str:
    """Mask a secret for API responses (keeps enough shape for the UI)."""
    if not value:
        return ""
    s = str(value)
    if len(s) <= 8:
        return "****" + s[-2:]
    return s[:4] + "****" + s[-4:]


def get_user_key(username: str, key_name: str) -> Optional[str]:
    """Return decrypted key for user, or None."""
    if not username or key_name not in ALLOWED_KEY_NAMES:
        return None
    with _LOCK:
        data = _load_raw()
        user_blob = (data.get("users") or {}).get(str(username).strip().lower()) or {}
        enc = user_blob.get(key_name)
        if not enc:
            return None
        try:
            return _decrypt(enc)
        except Exception as exc:
            logger.warning("Failed to decrypt %s for %s: %s", key_name, username, exc)
            return None


def get_user_keys_masked(username: str) -> Dict[str, str]:
    """Return all known keys for user, values masked (empty string if unset)."""
    out = {k: "" for k in ALLOWED_KEY_NAMES}
    if not username:
        return out
    with _LOCK:
        data = _load_raw()
        user_blob = (data.get("users") or {}).get(str(username).strip().lower()) or {}
        for key_name in ALLOWED_KEY_NAMES:
            enc = user_blob.get(key_name)
            if not enc:
                continue
            try:
                out[key_name] = mask_secret(_decrypt(enc))
            except Exception:
                # Decrypt failed (e.g. old key) — still show a placeholder so UI
                # knows a value exists and user can re-enter it.
                out[key_name] = "****"
    return out


def upsert_user_keys(username: str, keys: Dict[str, str]) -> Dict[str, str]:
    """
    Merge plaintext keys into the store (encrypt). Skips blank / masked values.
    Returns masked view after save.
    """
    if not username:
        raise ValueError("username required")
    uname = str(username).strip().lower()
    to_write = {}
    for key_name, value in (keys or {}).items():
        if key_name not in ALLOWED_KEY_NAMES:
            continue
        val = str(value or "").strip()
        if not val or "****" in val:
            continue
        to_write[key_name] = val
    if not to_write:
        raise ValueError("No keys to save. Paste a new token (masked values are not re-saved).")

    with _LOCK:
        # Ensure fernet is initialized before write
        _fernet()
        data = _load_raw()
        users = data.setdefault("users", {})
        blob = users.setdefault(uname, {})
        for key_name, val in to_write.items():
            blob[key_name] = _encrypt(val)
        _save_raw(data)
    return get_user_keys_masked(uname)


def reset_fernet_cache_for_tests():
    """Test helper: clear cached Fernet instance."""
    global _FERNET
    _FERNET = None
