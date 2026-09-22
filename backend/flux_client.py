"""Flux REST client used by Failed Testcase Analysis Quick Fix.

RegX never exposes Flux passwords or stored API keys to the browser. Flask
logs into Flux with the cached LDAP password, then posts Cursor/Gerrit keys
from user_keys and proxies quick-fix / ticket / resume calls.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_FLUX_API_BASE = "http://10.61.4.219"
REQUIRED_MCP_SERVERS = ("flux-jira-atlassian", "flux-gerrit")

Transport = Callable[..., Any]


class FluxError(Exception):
    """Flux API or setup failure with a Flask-ready payload."""

    def __init__(self, message: str, status_code: int = 502, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = int(status_code)
        self.payload = payload or {}

    def to_dict(self) -> Dict[str, Any]:
        body = {"error": self.message}
        body.update(self.payload)
        return body


class FluxKeySetupError(FluxError):
    def __init__(self, missing_key: str, message: Optional[str] = None):
        msg = message or (
            "Flux Quick Fix requires Flux username, Flux password, Cursor API key, and Gerrit HTTP password. "
            "Open User Settings → API Keys and add the missing credentials."
        )
        super().__init__(
            msg,
            status_code=403,
            payload={"require_key_setup": True, "missing_key": missing_key},
        )


_CLIENTS: Dict[str, "FluxClient"] = {}
_CLIENTS_LOCK = threading.Lock()


def flux_api_base() -> str:
    return (os.environ.get("FLUX_API_BASE") or DEFAULT_FLUX_API_BASE).strip().rstrip("/")


def extract_flux_token(payload: Any, headers: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Pull a Bearer token from common Flux login response shapes."""
    if isinstance(payload, dict):
        for key in ("access_token", "token", "jwt", "id_token"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for nested_key in ("data", "user", "auth"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                for key in ("access_token", "token", "jwt", "id_token"):
                    val = nested.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
    headers = headers or {}
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if str(auth).lower().startswith("bearer "):
        return str(auth)[7:].strip() or None
    return None


def missing_flux_keys(cursor_api_key: Optional[str], gerrit_http_password: Optional[str]) -> Optional[str]:
    if not (cursor_api_key or "").strip():
        return "cursor_api_key"
    if not (gerrit_http_password or "").strip():
        return "gerrit_http_password"
    return None


def build_credentials_payload(
    username: str,
    cursor_api_key: str,
    gerrit_http_password: str,
) -> Dict[str, str]:
    return {
        "cursor_api_key": cursor_api_key,
        "gerrit_username": (username or "").strip(),
        "gerrit_http_password": gerrit_http_password,
    }


def mcp_servers_ready(payload: Any, required: Tuple[str, ...] = REQUIRED_MCP_SERVERS) -> Tuple[bool, str]:
    servers = (payload or {}).get("servers") if isinstance(payload, dict) else None
    if not isinstance(servers, list):
        return False, "Flux MCP status did not include a servers list"
    by_name = {
        str(item.get("name") or ""): item
        for item in servers
        if isinstance(item, dict)
    }
    missing = []
    not_ready = []
    for name in required:
        item = by_name.get(name)
        if not item:
            missing.append(name)
            continue
        status = str(item.get("status") or "").lower()
        err = item.get("error")
        if status != "ready":
            detail = err or status or "unknown"
            not_ready.append("%s (%s)" % (name, detail))
    if missing:
        return False, "Flux MCP servers missing: %s" % ", ".join(missing)
    if not_ready:
        return False, "Flux MCP servers not ready: %s" % ", ".join(not_ready)
    return True, ""


def jira_key_verified(payload: Any, jira_key: str) -> bool:
    if not isinstance(payload, dict):
        return False
    results = payload.get("results") or {}
    if not isinstance(results, dict):
        return False
    key = (jira_key or "").strip()
    if key in results:
        return bool(results.get(key))
    upper = key.upper()
    for stored, value in results.items():
        if str(stored).upper() == upper:
            return bool(value)
    return False


def reset_flux_client_cache_for_tests() -> None:
    with _CLIENTS_LOCK:
        _CLIENTS.clear()


class FluxClient:
    def __init__(
        self,
        username: str,
        password: str,
        base_url: Optional[str] = None,
        transport: Optional[Transport] = None,
    ):
        self.username = (username or "").strip()
        self.password = password or ""
        self.base_url = (base_url or flux_api_base()).rstrip("/")
        self.transport = transport
        self.token: Optional[str] = None
        self._authed = False
        self._session = None if transport else requests.Session()

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        return headers

    def _raw_request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Any:
        url = self._url(path)
        try:
            if self.transport:
                return self.transport(
                    method=method.upper(),
                    url=url,
                    json=json_body,
                    headers=self._headers(),
                    timeout=timeout,
                )
            return self._session.request(
                method.upper(),
                url,
                json=json_body,
                headers=self._headers(),
                timeout=timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise FluxError(
                "Cannot reach Flux at %s. Check network or VPN." % self.base_url,
                503,
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise FluxError("Flux request timed out: %s %s" % (method, path), 504) from exc

    def _parse_response(self, resp: Any, method: str, path: str) -> Any:
        status = int(getattr(resp, "status_code", 0) or 0)
        try:
            payload = resp.json() if resp is not None else None
        except Exception:
            payload = None
        if status >= 400:
            message = None
            if isinstance(payload, dict):
                message = payload.get("error") or payload.get("message") or payload.get("detail")
            text = getattr(resp, "text", "") or ""
            # Flux 405 is a wrong-method call on Flux, not a missing Flask route.
            flask_status = 502 if status >= 500 or status == 405 else status
            raise FluxError(
                message or ("Flux %s %s failed (HTTP %s): %s" % (method, path, status, text[:300])),
                flask_status,
                {"flux_status": status, "flux_body": payload},
            )
        return payload if payload is not None else {}

    def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        retry_auth: bool = True,
    ) -> Any:
        resp = self._raw_request(method, path, json_body=json_body, timeout=timeout)
        if getattr(resp, "status_code", 0) == 401 and retry_auth and not path.rstrip("/").endswith("/auth/login"):
            self.login()
            resp = self._raw_request(method, path, json_body=json_body, timeout=timeout)
        return self._parse_response(resp, method, path)

    def login(self) -> Optional[str]:
        resp = self._raw_request(
            "POST",
            "/api/v1/auth/login",
            json_body={"username": self.username, "password": self.password},
            timeout=20,
        )
        payload = self._parse_response(resp, "POST", "/api/v1/auth/login")
        headers = getattr(resp, "headers", None) or {}
        token = extract_flux_token(payload, headers)
        if token:
            self.token = token
        elif not payload and not getattr(resp, "cookies", None):
            raise FluxError("Flux login returned an empty response", 502)
        self._authed = True
        return self.token

    def ensure_auth(self) -> None:
        if not self._authed:
            self.login()

    def sync_credentials(self, cursor_api_key: str, gerrit_http_password: str) -> Dict[str, Any]:
        self.ensure_auth()
        return self._request(
            "PUT",
            "/api/v1/credentials",
            json_body=build_credentials_payload(self.username, cursor_api_key, gerrit_http_password),
            timeout=20,
        ) or {}

    def check_mcp_status(self) -> Tuple[bool, str]:
        self.ensure_auth()
        payload = self._request("GET", "/api/v1/mcp-status", timeout=15) or {}
        return mcp_servers_ready(payload)

    def verify_jira(self, jira_key: str) -> bool:
        self.ensure_auth()
        payload = self._request(
            "POST",
            "/api/v1/verify-jira",
            json_body={"keys": [jira_key]},
            timeout=20,
        )
        return jira_key_verified(payload, jira_key)

    def quick_fix(
        self,
        jira_key: str,
        target_branch: str,
        log_url: Optional[str] = None,
        send_test_fix: bool = True,
        update_jira: bool = True,
        pause_for_review: bool = True,
    ) -> Dict[str, Any]:
        self.ensure_auth()
        body = {
            "jira_key": jira_key,
            "target_branch": target_branch,
            "log_url": log_url or None,
            "send_test_fix": bool(send_test_fix),
            "update_jira": bool(update_jira),
            "pause_for_review": bool(pause_for_review),
        }
        return self._request("POST", "/api/v1/quick-fix", json_body=body, timeout=30) or {}

    def get_ticket(self, record_id: int) -> Dict[str, Any]:
        self.ensure_auth()
        return self._request("GET", "/api/v1/tickets/%s" % int(record_id), timeout=30) or {}

    def resume_ticket(self, record_id: int) -> Dict[str, Any]:
        self.ensure_auth()
        return self._request("POST", "/api/v1/tickets/%s/resume" % int(record_id), timeout=30) or {}

    def start_quick_fix(
        self,
        jira_key: str,
        target_branch: str,
        log_url: Optional[str],
        cursor_api_key: str,
        gerrit_http_password: str,
        send_test_fix: bool = True,
        update_jira: bool = True,
        pause_for_review: bool = True,
    ) -> Dict[str, Any]:
        missing = missing_flux_keys(cursor_api_key, gerrit_http_password)
        if missing:
            raise FluxKeySetupError(missing)
        if not (jira_key or "").strip():
            raise FluxError("jira_key is required", 400)
        if not (target_branch or "").strip():
            raise FluxError("target_branch is required", 400)

        creds = self.sync_credentials(cursor_api_key, gerrit_http_password)
        if creds.get("setup_complete") is False:
            warnings = creds.get("warnings") or []
            raise FluxError(
                "Flux credential setup is incomplete",
                502,
                {"credentials": creds, "warnings": warnings},
            )
        ready, err = self.check_mcp_status()
        if not ready:
            raise FluxError(err or "Flux MCP servers are not ready", 502)
        if not self.verify_jira(jira_key.strip()):
            raise FluxError(
                "Jira key %s is not valid in Flux" % jira_key.strip(),
                400,
                {"jira_key": jira_key.strip()},
            )
        return self.quick_fix(
            jira_key=jira_key.strip(),
            target_branch=target_branch.strip(),
            log_url=(log_url or "").strip() or None,
            send_test_fix=send_test_fix,
            update_jira=update_jira,
            pause_for_review=pause_for_review,
        )


def get_client(username: str, password: str, base_url: Optional[str] = None) -> FluxClient:
    key = "%s@%s" % ((username or "").strip().lower(), (base_url or flux_api_base()))
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is None or client.password != password:
            client = FluxClient(username=username, password=password, base_url=base_url)
            _CLIENTS[key] = client
        return client
