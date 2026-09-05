"""
JARVIS Service for Node Management and Auto-Retrigger functionality

This service provides functionality to interact with JARVIS API for:
1. Searching nodes by hostname (GET /api/v1/nodes?search=...)
2. Disabling / enabling nodes by node id (PUT /api/v1/nodes/<id>)
3. Checking node status (is_enabled)
4. Auto-retriggering test cases after node fixes
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

JARVIS_BASE = os.getenv("JARVIS_BASE", "https://jarvis.eng.nutanix.com/api/v1").rstrip("/")
JITA_BASE = os.getenv("JITA_BASE", "https://jita.eng.nutanix.com/api/v2").rstrip("/")


def _jita_auth():
    """Resolve Jarvis/JITA basic-auth from env. Flask passes JITA_SVC_AUTH explicitly."""
    user = os.getenv("JITA_USERNAME") or os.getenv("JITA_SVC_USERNAME")
    password = os.getenv("JITA_PASSWORD") or os.getenv("JITA_SVC_PASSWORD")
    if user and password:
        return (user, password)
    return None


def _oid(val) -> str:
    """Normalize Mongo/JSON id fields to a string."""
    if not val:
        return ""
    if isinstance(val, dict):
        return str(val.get("$oid") or val.get("$id") or val.get("oid") or "")
    return str(val)


def _node_hostname(node: Dict[str, Any]) -> str:
    if not isinstance(node, dict):
        return ""
    net = node.get("network") or {}
    if isinstance(net, dict):
        host = net.get("hostname") or net.get("name") or ""
        if host:
            return str(host)
    return str(node.get("hostname") or node.get("name") or node.get("node_name") or "")


def _node_id(node: Dict[str, Any]) -> str:
    if not isinstance(node, dict):
        return ""
    return _oid(node.get("_id") or node.get("id") or node.get("node_id"))


def _is_enabled(node: Dict[str, Any]) -> Optional[bool]:
    if not isinstance(node, dict):
        return None
    if "is_enabled" in node:
        return bool(node.get("is_enabled"))
    if "enabled" in node:
        return bool(node.get("enabled"))
    return None


def build_disable_comment(rdm_link: Optional[str], disabled_by: str) -> str:
    """Jarvis comment format: RDM: <url> (Disabled by - user@nutanix.com)."""
    who = (disabled_by or "").strip() or "unknown"
    link = (rdm_link or "").strip()
    if link:
        return f"RDM: {link} (Disabled by - {who})"
    return f"RDM: node issue (Disabled by - {who})"


def build_enable_comment(rdm_link: Optional[str], enabled_by: str) -> str:
    who = (enabled_by or "").strip() or "unknown"
    link = (rdm_link or "").strip()
    if link:
        return f"RDM: {link} (Enabled by - {who})"
    return f"RDM: node re-enabled (Enabled by - {who})"


@dataclass
class JarvisNodeStatus:
    """Represents status of a node in JARVIS."""
    node_name: str
    pool_name: str
    status: str
    lab: str
    is_available: bool
    last_updated: datetime
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_name": self.node_name,
            "pool_name": self.pool_name,
            "status": self.status,
            "lab": self.lab,
            "is_available": self.is_available,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "details": self.details,
            "is_enabled": _is_enabled(self.details),
            "node_id": _node_id(self.details),
        }


@dataclass
class AutoRetriggerResult:
    """Result of auto-retrigger operation."""
    success: bool
    test_id: Optional[str]
    task_id: Optional[str]
    message: str
    retrigger_reason: str
    original_test_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "test_id": self.test_id,
            "task_id": self.task_id,
            "message": self.message,
            "retrigger_reason": self.retrigger_reason,
            "original_test_id": self.original_test_id,
        }


class JarvisNodeService:
    """Service for JARVIS node management and auto-retrigger operations."""

    def __init__(self, auth=None):
        self.jarvis_base = JARVIS_BASE
        self.jita_base = JITA_BASE
        self.auth = auth if auth is not None else _jita_auth()
        self.timeout = 30

    def search_nodes(self, hostname: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        GET /api/v1/nodes?search=<hostname>&find_editable=true&...

        Returns (nodes, error).
        """
        hostname = (hostname or "").strip()
        if not hostname:
            return [], "hostname is required"

        params = {
            "_dc": int(time.time() * 1000),
            "mine": "false",
            "search": hostname,
            "find_editable": "true",
            "only": "",
            "pool_exclusive": "false",
            "under_utilized": "",
            "common_pool": "",
            "page": 1,
            "start": 0,
            "limit": 25,
            "sort": "network.hostname",
            "dir": "ASC",
        }
        response = self._make_jarvis_request("GET", "nodes", params=params)
        if response is None:
            return [], "Jarvis GET /nodes failed"

        nodes = []
        if isinstance(response, list):
            nodes = response
        elif isinstance(response, dict):
            for key in ("data", "nodes", "items"):
                val = response.get(key)
                if isinstance(val, list):
                    nodes = val
                    break
            if not nodes and response.get("network"):
                nodes = [response]

        return nodes, None

    def find_node(self, hostname: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Find a node whose hostname matches ``hostname`` (exact, then substring)."""
        nodes, err = self.search_nodes(hostname)
        if err:
            return None, err
        if not nodes:
            return None, f"Node {hostname} not found in Jarvis"

        want = hostname.lower()
        exact = [n for n in nodes if _node_hostname(n).lower() == want]
        if exact:
            return exact[0], None
        partial = [n for n in nodes if want in _node_hostname(n).lower()]
        if partial:
            return partial[0], None
        return nodes[0], None

    def set_node_enabled(
        self,
        node_id: str,
        is_enabled: bool,
        comment: str,
    ) -> Dict[str, Any]:
        """PUT /api/v1/nodes/<id> with {is_enabled, comment}."""
        node_id = (node_id or "").strip()
        if not node_id:
            return {"success": False, "error": "node_id is required"}

        payload = {
            "is_enabled": bool(is_enabled),
            "comment": comment or "",
        }
        response = self._make_jarvis_request(
            "PUT",
            f"nodes/{node_id}",
            data=payload,
        )
        if response is None:
            return {
                "success": False,
                "error": "Jarvis PUT /nodes failed",
                "node_id": node_id,
                "payload": payload,
            }
        return {
            "success": True,
            "node_id": node_id,
            "is_enabled": bool(is_enabled),
            "comment": comment,
            "jarvis_response": response,
        }

    def disable_node_sync(
        self,
        node_name: str,
        rdm_link: Optional[str] = None,
        disabled_by: str = "",
        reason: str = "Rerun cause due to node issue",
    ) -> Dict[str, Any]:
        """
        Search Jarvis by hostname, PUT is_enabled=false on the node id,
        then GET again to confirm is_enabled is false.
        """
        try:
            logger.info("Attempting to disable Jarvis node: %s", node_name)
            node, err = self.find_node(node_name)
            if err or not node:
                return {
                    "success": False,
                    "error": err or f"Node {node_name} not found in Jarvis",
                    "node_name": node_name,
                }

            node_id = _node_id(node)
            hostname = _node_hostname(node) or node_name
            if not node_id:
                return {
                    "success": False,
                    "error": f"Jarvis node {hostname} has no id",
                    "node_name": hostname,
                    "node": node,
                }

            comment = build_disable_comment(rdm_link, disabled_by)
            put_result = self.set_node_enabled(node_id, False, comment)
            if not put_result.get("success"):
                put_result["node_name"] = hostname
                return put_result

            verified = self._verify_enabled(hostname, node_id, expected=False)
            return {
                "success": bool(verified.get("is_enabled") is False),
                "node_name": hostname,
                "node_id": node_id,
                "comment": comment,
                "rdm_link": rdm_link,
                "disabled_by": disabled_by,
                "reason": reason,
                "is_enabled": verified.get("is_enabled"),
                "already_disabled": _is_enabled(node) is False,
                "disabled_at": datetime.utcnow().isoformat(),
                "jarvis_response": put_result.get("jarvis_response"),
                "error": None if verified.get("is_enabled") is False else (
                    f"Jarvis PUT succeeded but is_enabled is {verified.get('is_enabled')}"
                ),
            }
        except Exception as e:
            logger.error("Error disabling node %s: %s", node_name, e)
            return {"success": False, "error": str(e), "node_name": node_name}

    def enable_node_sync(
        self,
        node_name: str,
        rdm_link: Optional[str] = None,
        enabled_by: str = "",
    ) -> Dict[str, Any]:
        try:
            node, err = self.find_node(node_name)
            if err or not node:
                return {
                    "success": False,
                    "error": err or f"Node {node_name} not found in Jarvis",
                    "node_name": node_name,
                }
            node_id = _node_id(node)
            hostname = _node_hostname(node) or node_name
            comment = build_enable_comment(rdm_link, enabled_by)
            put_result = self.set_node_enabled(node_id, True, comment)
            if not put_result.get("success"):
                put_result["node_name"] = hostname
                return put_result
            verified = self._verify_enabled(hostname, node_id, expected=True)
            return {
                "success": bool(verified.get("is_enabled") is True),
                "node_name": hostname,
                "node_id": node_id,
                "comment": comment,
                "is_enabled": verified.get("is_enabled"),
                "enabled_by": enabled_by,
            }
        except Exception as e:
            logger.error("Error enabling node %s: %s", node_name, e)
            return {"success": False, "error": str(e), "node_name": node_name}

    def _verify_enabled(self, hostname: str, node_id: str, expected: bool) -> Dict[str, Any]:
        node, err = self.find_node(hostname)
        if err or not node:
            return {"is_enabled": None, "error": err or "verify GET failed"}
        found_id = _node_id(node) or node_id
        return {
            "is_enabled": _is_enabled(node),
            "node_id": found_id,
            "hostname": _node_hostname(node) or hostname,
        }

    async def disable_node(
        self,
        node_name: str,
        rdm_link: Optional[str] = None,
        reason: str = "Auto-disabled due to RDM failure",
        disabled_by: str = "",
    ) -> Dict[str, Any]:
        """Async wrapper used by agent routes."""
        return self.disable_node_sync(
            node_name=node_name,
            rdm_link=rdm_link,
            disabled_by=disabled_by,
            reason=reason,
        )

    async def check_node_status(self, node_name: str) -> Optional[JarvisNodeStatus]:
        try:
            node, err = self.find_node(node_name)
            if err or not node:
                return None
            hostname = _node_hostname(node) or node_name
            enabled = _is_enabled(node)
            pool_obj = node.get("pool")
            if isinstance(pool_obj, dict):
                pool_name = pool_obj.get("name") or node.get("pool_name") or "unknown"
            else:
                pool_name = node.get("pool_name") or pool_obj or "unknown"
            lab = node.get("lab") or (node.get("location") or "unknown")
            return JarvisNodeStatus(
                node_name=hostname,
                pool_name=str(pool_name),
                status="enabled" if enabled else "disabled",
                lab=str(lab),
                is_available=bool(enabled),
                last_updated=datetime.utcnow(),
                details=node,
            )
        except Exception as e:
            logger.error("Error checking node status for %s: %s", node_name, e)
            return None

    async def auto_retrigger_testcase(
        self,
        original_test_result: Dict[str, Any],
        retrigger_reason: str = "Auto-retrigger after node fix",
    ) -> AutoRetriggerResult:
        """Auto-retrigger a test case after resolving node issues."""
        try:
            original_test_id = original_test_result.get("_id", {}).get("$oid", "")
            test_name = original_test_result.get("test", {}).get("name", "")

            logger.info("Auto-retriggering test: %s (Original ID: %s)", test_name, original_test_id)

            if not test_name:
                return AutoRetriggerResult(
                    success=False,
                    test_id=None,
                    task_id=None,
                    message="No test name found in original test result",
                    retrigger_reason=retrigger_reason,
                    original_test_id=original_test_id,
                )

            job_profile_id = self._extract_job_profile_id(original_test_result)
            if not job_profile_id:
                return AutoRetriggerResult(
                    success=False,
                    test_id=None,
                    task_id=None,
                    message="Could not extract job profile ID for retrigger",
                    retrigger_reason=retrigger_reason,
                    original_test_id=original_test_id,
                )

            trigger_result = await self._trigger_test_execution(
                job_profile_id=job_profile_id,
                test_name=test_name,
                original_test_result=original_test_result,
                retrigger_reason=retrigger_reason,
            )

            if trigger_result.get("success"):
                new_task_id = trigger_result.get("task_id")
                return AutoRetriggerResult(
                    success=True,
                    test_id=trigger_result.get("test_id"),
                    task_id=new_task_id,
                    message=f"Test successfully retriggered with task ID: {new_task_id}",
                    retrigger_reason=retrigger_reason,
                    original_test_id=original_test_id,
                )
            error_msg = trigger_result.get("error", "Unknown error during retrigger")
            return AutoRetriggerResult(
                success=False,
                test_id=None,
                task_id=None,
                message=error_msg,
                retrigger_reason=retrigger_reason,
                original_test_id=original_test_id,
            )
        except Exception as e:
            logger.error("Error in auto-retrigger: %s", e)
            return AutoRetriggerResult(
                success=False,
                test_id=None,
                task_id=None,
                message=f"Exception during retrigger: {str(e)}",
                retrigger_reason=retrigger_reason,
                original_test_id=original_test_result.get("_id", {}).get("$oid", ""),
            )

    def extract_node_from_rdm_analysis(self, rdm_analysis: Dict[str, Any]) -> Optional[str]:
        """Extract problematic node name from RDM failure analysis results."""
        try:
            if not isinstance(rdm_analysis, dict):
                return None
            explicit = rdm_analysis.get("failed_nodes") or rdm_analysis.get("failed_node")
            if isinstance(explicit, list) and explicit:
                return str(explicit[0]).strip() or None
            if isinstance(explicit, str) and explicit.strip():
                return explicit.strip()

            node_patterns = [
                r'Installer errors[:\s]+Nodes?:\s*([\w\-]+)',
                r'([\w\-]+):\s*Received\s+"fatal"\s+in\s+waiting\s+for\s+event',
                r'Nodes?:\s*([\w\-]+)',
                r'node[_\s]*([a-zA-Z0-9\-\.]+)',
                r'host[_\s]*([a-zA-Z0-9\-\.]+)',
                r'([a-zA-Z0-9\-\.]+)\.eng\.nutanix\.com',
            ]
            search_texts = [
                rdm_analysis.get("rdm_message", ""),
                rdm_analysis.get("error_message", ""),
                rdm_analysis.get("root_cause", ""),
                rdm_analysis.get("analysis_summary", ""),
                str(rdm_analysis.get("logs", "")),
            ]
            for text in search_texts:
                if not text:
                    continue
                for pattern in node_patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    if matches:
                        node_name = matches[0].strip()
                        if len(node_name) > 3 and node_name.lower() not in ("test", "error", "failed", "nodes"):
                            logger.info("Extracted node name from RDM analysis: %s", node_name)
                            return node_name
            return None
        except Exception as e:
            logger.error("Error extracting node from RDM analysis: %s", e)
            return None

    def _extract_job_profile_id(self, test_result: Dict[str, Any]) -> Optional[str]:
        try:
            agave_task = test_result.get("AgaveTask", {})
            if isinstance(agave_task, dict):
                job_profile_oid = agave_task.get("job_profile", {})
                if isinstance(job_profile_oid, dict) and "$oid" in job_profile_oid:
                    return job_profile_oid["$oid"]
                if isinstance(job_profile_oid, str):
                    return job_profile_oid
            jp_id = test_result.get("job_profile_id")
            if jp_id:
                if isinstance(jp_id, dict) and "$oid" in jp_id:
                    return jp_id["$oid"]
                return str(jp_id)
            return None
        except Exception as e:
            logger.error("Error extracting job profile ID: %s", e)
            return None

    async def _trigger_test_execution(
        self,
        job_profile_id: str,
        test_name: str,
        original_test_result: Dict[str, Any],
        retrigger_reason: str,
    ) -> Dict[str, Any]:
        try:
            payload = {
                "job_profile_id": job_profile_id,
                "tests": [test_name],
                "reason": f"Auto-retrigger: {retrigger_reason}",
                "triggered_by": "RegX-AI Auto Triage",
                "original_test_id": original_test_result.get("_id", {}).get("$oid", ""),
                "retrigger_timestamp": datetime.utcnow().isoformat(),
            }
            if "test_args" in original_test_result:
                payload["test_args"] = original_test_result["test_args"]

            response = requests.post(
                f"{self.jita_base}/trigger_tests",
                json=payload,
                auth=self.auth,
                verify=False,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code in (200, 201):
                result = response.json()
                return {
                    "success": True,
                    "task_id": result.get("task_id") or result.get("id"),
                    "test_id": result.get("test_id"),
                    "message": "Test execution triggered successfully",
                }
            return {
                "success": False,
                "error": f"JITA API error: {response.status_code} - {response.text[:200]}",
            }
        except Exception as e:
            logger.error("Error triggering test execution: %s", e)
            return {"success": False, "error": str(e)}

    def _make_jarvis_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            url = f"{self.jarvis_base}/{endpoint.lstrip('/')}"
            kwargs = {
                "auth": self.auth,
                "verify": False,
                "timeout": self.timeout,
                "headers": {"Content-Type": "application/json", "Accept": "application/json"},
            }
            if params:
                kwargs["params"] = params
            if data is not None:
                kwargs["json"] = data

            logger.info("Making %s request to JARVIS: %s", method.upper(), url)
            response = requests.request(method.upper(), url, **kwargs)
            logger.info("JARVIS API response: %s", response.status_code)

            if response.status_code in (200, 201, 204):
                try:
                    return response.json() if response.content else {"success": True}
                except json.JSONDecodeError:
                    return {"success": True, "status_code": response.status_code}
            logger.error("JARVIS API error: %s - %s", response.status_code, response.text[:500])
            return None
        except Exception as e:
            logger.error("Error making JARVIS request: %s", e)
            return None


async def disable_node(
    node_name: str,
    rdm_link: Optional[str] = None,
    reason: str = "RDM failure",
    disabled_by: str = "",
) -> Dict[str, Any]:
    service = JarvisNodeService()
    return await service.disable_node(node_name, rdm_link, reason, disabled_by=disabled_by)


async def auto_retrigger_test(
    original_test_result: Dict[str, Any],
    reason: str = "Node issue resolved",
) -> AutoRetriggerResult:
    service = JarvisNodeService()
    return await service.auto_retrigger_testcase(original_test_result, reason)


def extract_node_from_rdm(rdm_analysis: Dict[str, Any]) -> Optional[str]:
    service = JarvisNodeService()
    return service.extract_node_from_rdm_analysis(rdm_analysis)
