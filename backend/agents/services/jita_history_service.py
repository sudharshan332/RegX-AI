"""
JITA History API Service for Enhanced Intelligent Triage

This service provides functionality to check test execution history via JITA API
to determine if previous runs were successful on the same branch, which is used
for intermittent pattern detection in the enhanced triage flow.
"""

import asyncio
import json
import logging
import requests
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class JITATestHistory:
    """Represents test execution history from JITA."""
    test_id: str
    test_name: str
    status: str  # "Succeeded", "Failed", "Skipped", etc.
    branch: str
    start_time: datetime
    end_time: Optional[datetime]
    run_duration: int
    gbn: int
    agave_task_id: str
    is_official: bool
    
    @property
    def is_successful(self) -> bool:
        """Check if this test execution was successful."""
        return self.status.lower() in ("succeeded", "success", "passed")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "test_id": self.test_id,
            "test_name": self.test_name,
            "status": self.status,
            "branch": self.branch,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "run_duration": self.run_duration,
            "gbn": self.gbn,
            "agave_task_id": self.agave_task_id,
            "is_official": self.is_official,
            "is_successful": self.is_successful
        }


class JITAHistoryService:
    """Service for querying JITA test execution history."""
    
    def __init__(self):
        self.jita_base = "https://jita.eng.nutanix.com/api/v2"
        self.timeout = 30
        
        # Use service authentication (same as existing code)
        self.auth = None  # Will be set from environment or config
        
    async def check_previous_run_success(
        self, 
        test_name: str, 
        branch: str,
        current_test_id: str,
        limit: int = 5
    ) -> bool:
        """
        Check if the most recent previous run of this test was successful on the same branch.
        
        Args:
            test_name: Full test name (e.g., "cdp.stargate.enforceftc.test_oru.ORUTest.test_oru___rebuild_node_atfullcapacity")
            branch: Branch name (e.g., "ganges-7.6-stable")  
            current_test_id: Current test execution ID to exclude from history
            limit: Number of recent executions to fetch
            
        Returns:
            True if most recent previous run was successful, False otherwise
        """
        try:
            history = await self.get_test_execution_history(
                test_name=test_name,
                branch=branch,
                limit=limit + 1  # +1 to account for current execution
            )
            
            if not history:
                logger.warning(f"No history found for test {test_name} on branch {branch}")
                return False
            
            # Filter out current execution and find most recent previous run
            previous_runs = [
                run for run in history 
                if run.test_id != current_test_id
            ]
            
            if not previous_runs:
                logger.info(f"No previous runs found for test {test_name} (excluding current {current_test_id})")
                return False
            
            # Most recent previous run (history is sorted by start_time desc)
            previous_run = previous_runs[0]
            
            logger.info(
                f"Previous run status for {test_name}: {previous_run.status} "
                f"(ID: {previous_run.test_id}, GBN: {previous_run.gbn})"
            )
            
            return previous_run.is_successful
            
        except Exception as e:
            logger.error(f"Error checking previous run success for {test_name}: {str(e)}")
            return False
    
    async def get_test_execution_history(
        self,
        test_name: str,
        branch: str,
        limit: int = 20,
        official_only: bool = True
    ) -> List[JITATestHistory]:
        """
        Get test execution history from JITA API.
        
        Args:
            test_name: Full test name
            branch: Branch name
            limit: Maximum number of results
            official_only: Only include official test runs
            
        Returns:
            List of JITATestHistory objects sorted by start_time (most recent first)
        """
        try:
            # Build query parameters following the pattern from your example
            raw_query = {
                "test.name": test_name,
                "system_under_test.branch": branch
            }
            
            # Add official filter if requested
            if official_only:
                raw_query["AgaveTask.tester_tags"] = "official"
            
            params = {
                "start": 0,
                "limit": limit,
                "sort": "-start_time",  # Most recent first
                "raw_query": json.dumps(raw_query)
            }
            
            logger.info(f"Querying JITA history for {test_name} on {branch}")
            
            response = await self._make_jita_request("agave_test_results", params)
            
            if not response:
                return []
            
            # Parse response data
            data = response.get("data", [])
            total = response.get("total", 0)
            
            logger.info(f"Found {total} total executions, processing {len(data)} results")
            
            history = []
            for item in data:
                try:
                    hist_item = self._parse_jita_test_result(item)
                    if hist_item:
                        history.append(hist_item)
                except Exception as e:
                    logger.warning(f"Error parsing JITA result item: {str(e)}")
                    continue
            
            return history
            
        except Exception as e:
            logger.error(f"Error fetching test history from JITA: {str(e)}")
            return []
    
    async def get_intermittent_analysis(
        self,
        test_name: str,
        branch: str,
        window_hours: int = 72
    ) -> Dict[str, Any]:
        """
        Analyze test execution history for intermittent patterns.
        
        Args:
            test_name: Full test name
            branch: Branch name  
            window_hours: Time window to analyze (default 72 hours)
            
        Returns:
            Dictionary with intermittent analysis results
        """
        try:
            # Get larger history for pattern analysis
            history = await self.get_test_execution_history(
                test_name=test_name,
                branch=branch,
                limit=50,  # More data for better analysis
                official_only=True
            )
            
            if len(history) < 3:
                return {
                    "sufficient_data": False,
                    "total_runs": len(history),
                    "message": "Insufficient history for intermittent analysis"
                }
            
            # Filter to recent window
            cutoff_time = datetime.utcnow().timestamp() - (window_hours * 3600)
            recent_history = [
                run for run in history 
                if run.start_time.timestamp() > cutoff_time
            ]
            
            # Analyze patterns
            total_runs = len(recent_history)
            successful_runs = len([run for run in recent_history if run.is_successful])
            failed_runs = total_runs - successful_runs
            
            if total_runs == 0:
                success_rate = 0.0
            else:
                success_rate = successful_runs / total_runs
            
            # Check for alternating pattern (intermittent indicator)
            alternating_pattern = self._detect_alternating_pattern(recent_history)
            
            # Determine if this looks intermittent
            is_intermittent = (
                success_rate > 0.2 and success_rate < 0.8 and  # Mixed results
                total_runs >= 3 and  # Sufficient data
                alternating_pattern  # Shows alternating behavior
            )
            
            return {
                "sufficient_data": True,
                "total_runs": total_runs,
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "success_rate": success_rate,
                "alternating_pattern": alternating_pattern,
                "is_intermittent": is_intermittent,
                "confidence": self._calculate_intermittent_confidence(
                    success_rate, total_runs, alternating_pattern
                ),
                "window_hours": window_hours,
                "recent_executions": [run.to_dict() for run in recent_history[:10]]
            }
            
        except Exception as e:
            logger.error(f"Error in intermittent analysis: {str(e)}")
            return {
                "sufficient_data": False,
                "error": str(e)
            }
    
    def _parse_jita_test_result(self, item: Dict[str, Any]) -> Optional[JITATestHistory]:
        """Parse a single JITA test result item into JITATestHistory."""
        try:
            # Extract key fields from JITA response
            test_id = item.get("_id", {}).get("$oid", "")
            test_name = item.get("test", {}).get("name", "")
            status = item.get("status", "")
            branch = item.get("system_under_test", {}).get("branch", "")
            
            # Parse timestamps
            start_time_data = item.get("start_time", {})
            if isinstance(start_time_data, dict) and "$date" in start_time_data:
                start_time = datetime.fromtimestamp(start_time_data["$date"] / 1000)
            else:
                start_time = datetime.utcnow()
            
            end_time_data = item.get("end_time", {})
            end_time = None
            if isinstance(end_time_data, dict) and "$date" in end_time_data:
                end_time = datetime.fromtimestamp(end_time_data["$date"] / 1000)
            
            # Other fields
            run_duration = item.get("run_duration", 0)
            gbn = item.get("gbn", 0)
            agave_task_id = item.get("agave_task_id", {}).get("$oid", "")
            
            # Check if this is an official run
            tester_tags = item.get("AgaveTask", {}).get("tester_tags", [])
            is_official = "official" in tester_tags
            
            return JITATestHistory(
                test_id=test_id,
                test_name=test_name,
                status=status,
                branch=branch,
                start_time=start_time,
                end_time=end_time,
                run_duration=run_duration,
                gbn=gbn,
                agave_task_id=agave_task_id,
                is_official=is_official
            )
            
        except Exception as e:
            logger.error(f"Error parsing JITA test result: {str(e)}")
            return None
    
    def _detect_alternating_pattern(self, history: List[JITATestHistory]) -> bool:
        """Detect if there's an alternating success/failure pattern."""
        if len(history) < 3:
            return False
        
        # Look at the most recent 6 executions for alternating pattern
        recent = history[:6]
        alternations = 0
        
        for i in range(len(recent) - 1):
            if recent[i].is_successful != recent[i + 1].is_successful:
                alternations += 1
        
        # If more than half of adjacent pairs alternate, consider it alternating
        return alternations >= (len(recent) - 1) // 2
    
    def _calculate_intermittent_confidence(
        self, 
        success_rate: float, 
        total_runs: int, 
        alternating_pattern: bool
    ) -> float:
        """Calculate confidence score for intermittent classification."""
        confidence = 0.0
        
        # Base confidence from success rate (intermittent should be mixed)
        if 0.2 <= success_rate <= 0.8:
            # Closer to 50% = higher confidence in intermittency
            rate_confidence = 1.0 - abs(success_rate - 0.5) * 2
            confidence += rate_confidence * 0.5
        
        # Boost from sufficient data
        if total_runs >= 5:
            confidence += 0.3
        elif total_runs >= 3:
            confidence += 0.1
        
        # Boost from alternating pattern
        if alternating_pattern:
            confidence += 0.2
        
        return min(confidence, 1.0)
    
    async def _make_jita_request(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make authenticated request to JITA API."""
        try:
            url = f"{self.jita_base}/{endpoint}"
            
            # Use existing JITA authentication method from your codebase
            # This would need to be configured based on your auth setup
            response = requests.get(
                url,
                params=params,
                timeout=self.timeout,
                verify=False  # Following your existing pattern
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"JITA API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error making JITA request: {str(e)}")
            return None


# Utility functions for integration with intelligent triage agent

async def check_previous_run_success(
    test_name: str,
    branch: str, 
    current_test_id: str
) -> bool:
    """
    Convenience function to check if previous run was successful.
    
    Usage in intelligent triage agent:
        previous_success = await check_previous_run_success(
            test_name="cdp.stargate.test.MyTest.test_method", 
            branch="ganges-7.6-stable",
            current_test_id="6a0ef120b5e475c9eb2e25ea"
        )
    """
    service = JITAHistoryService()
    return await service.check_previous_run_success(test_name, branch, current_test_id)


async def get_intermittent_analysis(
    test_name: str,
    branch: str
) -> Dict[str, Any]:
    """
    Convenience function to get intermittent pattern analysis.
    
    Usage:
        analysis = await get_intermittent_analysis(
            test_name="cdp.stargate.test.MyTest.test_method",
            branch="ganges-7.6-stable" 
        )
        if analysis["is_intermittent"]:
            # Handle intermittent pattern
    """
    service = JITAHistoryService()
    return await service.get_intermittent_analysis(test_name, branch)