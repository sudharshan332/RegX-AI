"""
JARVIS Service for Node Management and Auto-Retrigger functionality

This service provides functionality to interact with JARVIS API for:
1. Disabling problematic nodes after RDM failure analysis
2. Checking node status and health
3. Auto-retriggering test cases after node fixes
"""

import asyncio
import json
import logging
import requests
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# Import constants from main Flask app
try:
    from ...test_flask import JARVIS_BASE, JITA_SVC_AUTH, JITA_BASE
except ImportError:
    # Fallback values for testing
    JARVIS_BASE = "https://jarvis.eng.nutanix.com/api/v1"
    JITA_BASE = "https://jita.eng.nutanix.com/api/v2"
    JITA_SVC_AUTH = None


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
        """Convert to dictionary for JSON serialization."""
        return {
            "node_name": self.node_name,
            "pool_name": self.pool_name,
            "status": self.status,
            "lab": self.lab,
            "is_available": self.is_available,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "details": self.details
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
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "test_id": self.test_id,
            "task_id": self.task_id,
            "message": self.message,
            "retrigger_reason": self.retrigger_reason,
            "original_test_id": self.original_test_id
        }


class JarvisNodeService:
    """Service for JARVIS node management and auto-retrigger operations."""
    
    def __init__(self):
        self.jarvis_base = JARVIS_BASE
        self.jita_base = JITA_BASE
        self.auth = JITA_SVC_AUTH
        self.timeout = 30
    
    async def disable_node(
        self, 
        node_name: str, 
        rdm_link: Optional[str] = None,
        reason: str = "Auto-disabled due to RDM failure"
    ) -> Dict[str, Any]:
        """
        Disable a node in JARVIS using the correct API format.
        
        Args:
            node_name: Name of the node to disable (e.g., "ARACHNE-2")
            rdm_link: RDM deployment link (e.g., "https://rdm.eng.nutanix.com/scheduled_deployments/6a46739892fce97bbf2f27a6")
            reason: Base reason for disabling the node
            
        Returns:
            Dictionary with operation result
        """
        try:
            logger.info(f"Attempting to disable node: {node_name}")
            
            # Construct comment with RDM link if provided
            if rdm_link:
                comment = f"Node disabled due to RDM failure: {rdm_link}"
            else:
                comment = f"Node disabled due to RDM failure: {reason}"
            
            # Prepare disable request payload using correct JARVIS API format
            disable_payload = {
                "is_enabled": False,
                "comment": comment
            }
            
            # Make PUT request to JARVIS API using correct endpoint format
            response = await self._make_jarvis_request(
                method="PUT",
                endpoint=f"nodes/{node_name}",
                data=disable_payload
            )
            
            if response is not None:
                logger.info(f"Successfully disabled node {node_name}")
                return {
                    "success": True,
                    "node_name": node_name,
                    "comment": comment,
                    "rdm_link": rdm_link,
                    "disabled_at": datetime.utcnow().isoformat(),
                    "jarvis_response": response
                }
            else:
                logger.error(f"Failed to disable node {node_name}: No response or error from JARVIS")
                return {
                    "success": False,
                    "error": "No response from JARVIS API",
                    "node_name": node_name
                }
                
        except Exception as e:
            logger.error(f"Error disabling node {node_name}: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "node_name": node_name
            }
    
    async def check_node_status(self, node_name: str) -> Optional[JarvisNodeStatus]:
        """
        Check the status of a node in JARVIS.
        
        Args:
            node_name: Name of the node to check
            
        Returns:
            JarvisNodeStatus object or None if not found
        """
        try:
            node_info = await self._find_node_in_jarvis(node_name)
            if not node_info:
                return None
            
            status = node_info.get("status", "unknown")
            pool_name = node_info.get("pool_name", node_info.get("pool", "unknown"))
            lab = node_info.get("lab", "unknown")
            
            # Parse availability based on status
            available_statuses = ["available", "online", "ready", "active"]
            is_available = status.lower() in available_statuses
            
            # Parse timestamp
            last_updated = datetime.utcnow()
            if "updated_at" in node_info:
                try:
                    timestamp_data = node_info["updated_at"]
                    if isinstance(timestamp_data, dict) and "$date" in timestamp_data:
                        last_updated = datetime.fromtimestamp(timestamp_data["$date"] / 1000)
                    elif isinstance(timestamp_data, str):
                        last_updated = datetime.fromisoformat(timestamp_data.replace('Z', '+00:00'))
                except Exception:
                    pass
            
            return JarvisNodeStatus(
                node_name=node_name,
                pool_name=pool_name,
                status=status,
                lab=lab,
                is_available=is_available,
                last_updated=last_updated,
                details=node_info
            )
            
        except Exception as e:
            logger.error(f"Error checking node status for {node_name}: {str(e)}")
            return None
    
    async def auto_retrigger_testcase(
        self, 
        original_test_result: Dict[str, Any],
        retrigger_reason: str = "Auto-retrigger after node fix"
    ) -> AutoRetriggerResult:
        """
        Auto-retrigger a test case after resolving node issues.
        
        Args:
            original_test_result: Original test result data from JITA
            retrigger_reason: Reason for retriggering
            
        Returns:
            AutoRetriggerResult object
        """
        try:
            original_test_id = original_test_result.get("_id", {}).get("$oid", "")
            test_name = original_test_result.get("test", {}).get("name", "")
            
            logger.info(f"Auto-retriggering test: {test_name} (Original ID: {original_test_id})")
            
            if not test_name:
                return AutoRetriggerResult(
                    success=False,
                    test_id=None,
                    task_id=None,
                    message="No test name found in original test result",
                    retrigger_reason=retrigger_reason,
                    original_test_id=original_test_id
                )
            
            # Extract necessary information for retrigger
            job_profile_id = self._extract_job_profile_id(original_test_result)
            if not job_profile_id:
                return AutoRetriggerResult(
                    success=False,
                    test_id=None,
                    task_id=None,
                    message="Could not extract job profile ID for retrigger",
                    retrigger_reason=retrigger_reason,
                    original_test_id=original_test_id
                )
            
            # Trigger new test execution via JITA
            trigger_result = await self._trigger_test_execution(
                job_profile_id=job_profile_id,
                test_name=test_name,
                original_test_result=original_test_result,
                retrigger_reason=retrigger_reason
            )
            
            if trigger_result.get("success"):
                new_task_id = trigger_result.get("task_id")
                logger.info(f"Successfully retriggered test {test_name} with task ID: {new_task_id}")
                
                return AutoRetriggerResult(
                    success=True,
                    test_id=trigger_result.get("test_id"),
                    task_id=new_task_id,
                    message=f"Test successfully retriggered with task ID: {new_task_id}",
                    retrigger_reason=retrigger_reason,
                    original_test_id=original_test_id
                )
            else:
                error_msg = trigger_result.get("error", "Unknown error during retrigger")
                return AutoRetriggerResult(
                    success=False,
                    test_id=None,
                    task_id=None,
                    message=error_msg,
                    retrigger_reason=retrigger_reason,
                    original_test_id=original_test_id
                )
                
        except Exception as e:
            logger.error(f"Error in auto-retrigger: {str(e)}")
            return AutoRetriggerResult(
                success=False,
                test_id=None,
                task_id=None,
                message=f"Exception during retrigger: {str(e)}",
                retrigger_reason=retrigger_reason,
                original_test_id=original_test_result.get("_id", {}).get("$oid", "")
            )
    
    def extract_node_from_rdm_analysis(self, rdm_analysis: Dict[str, Any]) -> Optional[str]:
        """
        Extract problematic node name from RDM failure analysis results.
        
        Args:
            rdm_analysis: RDM analysis results from triage-rdm-deployment-failure skill
            
        Returns:
            Node name if found, None otherwise
        """
        try:
            # Look for node information in various places in RDM analysis
            node_patterns = [
                r'node[_\s]*([a-zA-Z0-9\-\.]+)',
                r'host[_\s]*([a-zA-Z0-9\-\.]+)',
                r'server[_\s]*([a-zA-Z0-9\-\.]+)',
                r'([a-zA-Z0-9\-\.]+)\.eng\.nutanix\.com',
                r'phx\d+-(\w+\d+)',
            ]
            
            # Search in error messages and logs
            search_texts = [
                rdm_analysis.get("error_message", ""),
                rdm_analysis.get("root_cause", ""),
                rdm_analysis.get("analysis_summary", ""),
                str(rdm_analysis.get("logs", ""))
            ]
            
            for text in search_texts:
                if not text:
                    continue
                    
                for pattern in node_patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    if matches:
                        node_name = matches[0].strip()
                        # Validate node name format
                        if len(node_name) > 3 and node_name not in ['test', 'error', 'failed']:
                            logger.info(f"Extracted node name from RDM analysis: {node_name}")
                            return node_name
            
            # Look in structured data
            if "node_info" in rdm_analysis:
                node_info = rdm_analysis["node_info"]
                if isinstance(node_info, dict):
                    return node_info.get("name") or node_info.get("hostname")
                elif isinstance(node_info, str):
                    return node_info
            
            logger.warning("Could not extract node name from RDM analysis")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting node from RDM analysis: {str(e)}")
            return None
    
    async def _find_node_in_jarvis(self, node_name: str) -> Optional[Dict[str, Any]]:
        """Find a node in JARVIS by name."""
        try:
            # Search for node in pools
            search_params = {
                "search": node_name,
                "limit": 10
            }
            
            response = await self._make_jarvis_request(
                method="GET",
                endpoint="nodes/search",
                params=search_params
            )
            
            if response and "nodes" in response:
                nodes = response["nodes"]
                # Look for exact match first, then partial match
                for node in nodes:
                    if node.get("name", "").lower() == node_name.lower():
                        return node
                
                # If no exact match, return first partial match
                if nodes:
                    return nodes[0]
            
            # Alternative: search in pools
            pool_response = await self._make_jarvis_request(
                method="GET",
                endpoint="pools",
                params={"name_contains": node_name}
            )
            
            if pool_response and "data" in pool_response:
                for pool in pool_response["data"]:
                    if "nodes" in pool:
                        for node in pool["nodes"]:
                            if node_name.lower() in node.get("name", "").lower():
                                return node
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding node in JARVIS: {str(e)}")
            return None
    
    def _extract_job_profile_id(self, test_result: Dict[str, Any]) -> Optional[str]:
        """Extract job profile ID from test result."""
        try:
            # Try multiple possible locations
            agave_task = test_result.get("AgaveTask", {})
            if isinstance(agave_task, dict):
                job_profile_oid = agave_task.get("job_profile", {})
                if isinstance(job_profile_oid, dict) and "$oid" in job_profile_oid:
                    return job_profile_oid["$oid"]
                elif isinstance(job_profile_oid, str):
                    return job_profile_oid
            
            # Alternative locations
            jp_id = test_result.get("job_profile_id")
            if jp_id:
                if isinstance(jp_id, dict) and "$oid" in jp_id:
                    return jp_id["$oid"]
                return str(jp_id)
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting job profile ID: {str(e)}")
            return None
    
    async def _trigger_test_execution(
        self, 
        job_profile_id: str,
        test_name: str,
        original_test_result: Dict[str, Any],
        retrigger_reason: str
    ) -> Dict[str, Any]:
        """Trigger new test execution via JITA API."""
        try:
            # Prepare trigger payload following JITA API format
            payload = {
                "job_profile_id": job_profile_id,
                "tests": [test_name],
                "reason": f"Auto-retrigger: {retrigger_reason}",
                "triggered_by": "RegX-AI Auto Triage",
                "original_test_id": original_test_result.get("_id", {}).get("$oid", ""),
                "retrigger_timestamp": datetime.utcnow().isoformat()
            }
            
            # Add any specific parameters from original test
            if "test_args" in original_test_result:
                payload["test_args"] = original_test_result["test_args"]
            
            # Make request to JITA to trigger test
            response = requests.post(
                f"{self.jita_base}/trigger_tests",
                json=payload,
                auth=self.auth,
                verify=False,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in (200, 201):
                result = response.json()
                return {
                    "success": True,
                    "task_id": result.get("task_id") or result.get("id"),
                    "test_id": result.get("test_id"),
                    "message": "Test execution triggered successfully"
                }
            else:
                return {
                    "success": False,
                    "error": f"JITA API error: {response.status_code} - {response.text[:200]}"
                }
                
        except Exception as e:
            logger.error(f"Error triggering test execution: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _make_jarvis_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Make authenticated request to JARVIS API."""
        try:
            url = f"{self.jarvis_base}/{endpoint.lstrip('/')}"
            
            kwargs = {
                "auth": self.auth,
                "verify": False,
                "timeout": self.timeout,
                "headers": {"Content-Type": "application/json"}
            }
            
            if params:
                kwargs["params"] = params
            if data:
                kwargs["json"] = data
            
            logger.info(f"Making {method.upper()} request to JARVIS: {url}")
            logger.debug(f"Request payload: {data}")
            
            response = requests.request(method.upper(), url, **kwargs)
            
            logger.info(f"JARVIS API response: {response.status_code}")
            
            if response.status_code in (200, 201, 204):
                # Handle both JSON and non-JSON responses
                try:
                    return response.json() if response.content else {"success": True}
                except json.JSONDecodeError:
                    # Some APIs return empty response on success
                    return {"success": True, "status_code": response.status_code}
            else:
                logger.error(f"JARVIS API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error making JARVIS request: {str(e)}")
            return None


# Convenience functions for integration

async def disable_node(
    node_name: str, 
    rdm_link: Optional[str] = None, 
    reason: str = "RDM failure"
) -> Dict[str, Any]:
    """
    Convenience function to disable a node in JARVIS.
    
    Usage in intelligent triage agent:
        result = await disable_node("ARACHNE-2", 
                                   "https://rdm.eng.nutanix.com/scheduled_deployments/6a46739892fce97bbf2f27a6")
    """
    service = JarvisNodeService()
    return await service.disable_node(node_name, rdm_link, reason)


async def auto_retrigger_test(
    original_test_result: Dict[str, Any], 
    reason: str = "Node issue resolved"
) -> AutoRetriggerResult:
    """
    Convenience function to auto-retrigger a test.
    
    Usage:
        result = await auto_retrigger_test(test_result, "Node disabled and retriggering")
    """
    service = JarvisNodeService()
    return await service.auto_retrigger_testcase(original_test_result, reason)


def extract_node_from_rdm(rdm_analysis: Dict[str, Any]) -> Optional[str]:
    """
    Convenience function to extract node name from RDM analysis.
    
    Usage:
        node_name = extract_node_from_rdm(rdm_analysis_results)
    """
    service = JarvisNodeService()
    return service.extract_node_from_rdm_analysis(rdm_analysis)