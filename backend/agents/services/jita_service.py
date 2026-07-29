"""
JITA API Service for RegX-AI Agent Framework

This service provides integration with the JITA API for detailed test result analysis,
step log examination, and exception analysis for intelligent test failure triage.
"""

import asyncio
import aiohttp
import json
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import re
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class JITAStepLog:
    """Represents a single step log entry from JITA."""
    step_number: int
    timestamp: Optional[str]
    command: Optional[str]
    output: str
    status: str
    duration: Optional[int]
    error_level: str  # "info", "warning", "error", "fatal"


@dataclass
class JITAException:
    """Represents exception information from JITA."""
    exception_type: Optional[str]
    message: str
    traceback: Optional[str]
    stage: Optional[str]
    timestamp: Optional[str]
    
    def get_error_signature(self) -> str:
        """Generate a signature for pattern matching."""
        parts = []
        if self.exception_type:
            parts.append(self.exception_type)
        if self.message:
            # Clean message for signature
            cleaned = re.sub(r'\d+', '[NUMBER]', self.message)
            cleaned = re.sub(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', '[UUID]', cleaned)
            parts.append(cleaned[:200])
        return " | ".join(parts)


@dataclass
class JITAAnalysisResult:
    """Complete JITA analysis result."""
    test_id: str
    success: bool
    api_response_time: float
    
    # Test execution info
    test_status: str
    execution_time_ms: Optional[int]
    start_time: Optional[str]
    end_time: Optional[str]
    
    # Failure analysis
    failure_stage: Optional[str]
    failure_step: Optional[int]
    primary_exception: Optional[JITAException]
    all_exceptions: List[JITAException]
    
    # Step logs
    step_logs: List[JITAStepLog]
    error_steps: List[int]
    warning_steps: List[int]
    
    # Environment and metadata
    environment_info: Dict[str, Any]
    test_metadata: Dict[str, Any]
    
    # Analysis metadata
    api_url: str
    processed_at: str
    raw_response: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "test_id": self.test_id,
            "success": self.success,
            "api_response_time": self.api_response_time,
            "test_status": self.test_status,
            "execution_time_ms": self.execution_time_ms,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "failure_stage": self.failure_stage,
            "failure_step": self.failure_step,
            "primary_exception": asdict(self.primary_exception) if self.primary_exception else None,
            "all_exceptions": [asdict(exc) for exc in self.all_exceptions],
            "step_logs": [asdict(log) for log in self.step_logs],
            "error_steps": self.error_steps,
            "warning_steps": self.warning_steps,
            "environment_info": self.environment_info,
            "test_metadata": self.test_metadata,
            "api_url": self.api_url,
            "processed_at": self.processed_at
        }


class JITAService:
    """Service for JITA API integration and test result analysis."""
    
    def __init__(self):
        self.base_url = "https://jita-phx1-webserver-2.eng.nutanix.com/api/v2"
        self.timeout = 30
        self.max_retries = 3
        self.retry_delay_base = 2
        
        # Response caching to avoid redundant calls
        self._cache = {}
        self._cache_ttl = 3600  # 1 hour
        
    async def get_test_results(self, test_id: str) -> Optional[JITAAnalysisResult]:
        """
        Fetch and analyze test results from JITA API.
        
        Args:
            test_id: The test ID to fetch results for
            
        Returns:
            JITAAnalysisResult or None if fetch failed
        """
        if not test_id:
            logger.error("No test_id provided for JITA API call")
            return None
        
        # Check cache first
        cache_key = f"jita_test_{test_id}"
        cached_result = self._get_from_cache(cache_key)
        if cached_result:
            logger.debug(f"Returning cached JITA result for {test_id}")
            return cached_result
        
        # Fetch from API
        start_time = time.time()
        api_url = f"{self.base_url}/agave_test_results/{test_id}"
        
        try:
            raw_response = await self._fetch_with_retry(api_url)
            if raw_response is None:
                return None
            
            response_time = time.time() - start_time
            
            # Parse and analyze response
            result = await self._parse_jita_response(
                test_id, raw_response, api_url, response_time
            )
            
            # Cache successful results
            if result and result.success:
                self._set_cache(cache_key, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Unexpected error fetching JITA results for {test_id}: {str(e)}")
            return None
    
    async def analyze_step_logs(self, test_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze step logs for failure points and patterns.
        
        Args:
            test_result: Test result containing step logs
            
        Returns:
            Analysis results with failure points and patterns
        """
        test_id = test_result.get("test_id")
        
        # Get detailed results from JITA
        jita_result = await self.get_test_results(test_id) if test_id else None
        
        if not jita_result:
            # Fallback to basic analysis with available data
            return self._analyze_basic_logs(test_result)
        
        return self._analyze_detailed_logs(jita_result)
    
    async def extract_exception_analysis(self, test_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and analyze exception summaries and details.
        
        Args:
            test_result: Test result data
            
        Returns:
            Exception analysis with categorization and signatures
        """
        test_id = test_result.get("test_id")
        
        # Get detailed results from JITA
        jita_result = await self.get_test_results(test_id) if test_id else None
        
        if not jita_result:
            # Fallback to basic exception analysis
            return self._analyze_basic_exceptions(test_result)
        
        return self._analyze_detailed_exceptions(jita_result)
    
    def build_glean_search_query(self, jita_result: JITAAnalysisResult) -> str:
        """
        Build a targeted Glean search query from JITA analysis.
        
        Args:
            jita_result: JITA analysis result
            
        Returns:
            Optimized search query for Glean
        """
        query_parts = []
        
        # Add primary exception info
        if jita_result.primary_exception:
            signature = jita_result.primary_exception.get_error_signature()
            if signature and len(signature) > 10:
                query_parts.append(signature[:100])
        
        # Add failure stage
        if jita_result.failure_stage:
            query_parts.append(f"stage:{jita_result.failure_stage}")
        
        # Add key error indicators from logs
        error_keywords = self._extract_error_keywords(jita_result.step_logs)
        query_parts.extend(error_keywords[:3])  # Limit to top 3
        
        # Add environment context if relevant
        env_info = jita_result.environment_info
        if env_info.get("cluster_type"):
            query_parts.append(f"cluster:{env_info['cluster_type']}")
        
        return " ".join(query_parts) if query_parts else "test failure analysis"
    
    async def _fetch_with_retry(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch data from JITA API with retry logic."""
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                timeout_config = aiohttp.ClientTimeout(total=self.timeout)
                async with aiohttp.ClientSession(timeout=timeout_config) as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            logger.debug(f"JITA API success on attempt {attempt + 1}")
                            return data
                        elif response.status == 404:
                            logger.warning(f"Test not found in JITA API: {url}")
                            return None
                        else:
                            logger.warning(f"JITA API returned status {response.status} on attempt {attempt + 1}")
                            
            except asyncio.TimeoutError as e:
                last_exception = e
                logger.warning(f"JITA API timeout on attempt {attempt + 1}")
            except aiohttp.ClientError as e:
                last_exception = e
                logger.warning(f"JITA API client error on attempt {attempt + 1}: {str(e)}")
            except Exception as e:
                last_exception = e
                logger.error(f"Unexpected JITA API error on attempt {attempt + 1}: {str(e)}")
            
            # Wait before retry (exponential backoff)
            if attempt < self.max_retries - 1:
                delay = self.retry_delay_base ** attempt
                await asyncio.sleep(delay)
        
        logger.error(f"Failed to fetch from JITA API after {self.max_retries} attempts: {str(last_exception)}")
        return None
    
    async def _parse_jita_response(
        self,
        test_id: str,
        raw_response: Dict[str, Any],
        api_url: str,
        response_time: float
    ) -> JITAAnalysisResult:
        """Parse JITA API response into structured format."""
        try:
            # Extract basic test info
            test_status = raw_response.get("status", "unknown").lower()
            execution_time = raw_response.get("execution_time_ms")
            start_time = raw_response.get("start_time")
            end_time = raw_response.get("end_time")
            
            # Parse failure information
            failure_stage = self._extract_failure_stage(raw_response)
            failure_step = self._extract_failure_step(raw_response)
            
            # Parse exceptions
            all_exceptions = self._parse_exceptions(raw_response)
            primary_exception = all_exceptions[0] if all_exceptions else None
            
            # Parse step logs
            step_logs = self._parse_step_logs(raw_response)
            error_steps, warning_steps = self._categorize_log_steps(step_logs)
            
            # Extract environment and metadata
            environment_info = self._extract_environment_info(raw_response)
            test_metadata = self._extract_test_metadata(raw_response)
            
            return JITAAnalysisResult(
                test_id=test_id,
                success=True,
                api_response_time=response_time,
                test_status=test_status,
                execution_time_ms=execution_time,
                start_time=start_time,
                end_time=end_time,
                failure_stage=failure_stage,
                failure_step=failure_step,
                primary_exception=primary_exception,
                all_exceptions=all_exceptions,
                step_logs=step_logs,
                error_steps=error_steps,
                warning_steps=warning_steps,
                environment_info=environment_info,
                test_metadata=test_metadata,
                api_url=api_url,
                processed_at=datetime.utcnow().isoformat(),
                raw_response=raw_response
            )
            
        except Exception as e:
            logger.error(f"Error parsing JITA response for {test_id}: {str(e)}")
            # Return minimal result with error indication
            return JITAAnalysisResult(
                test_id=test_id,
                success=False,
                api_response_time=response_time,
                test_status="parse_error",
                execution_time_ms=None,
                start_time=None,
                end_time=None,
                failure_stage="parsing_failed",
                failure_step=None,
                primary_exception=None,
                all_exceptions=[],
                step_logs=[],
                error_steps=[],
                warning_steps=[],
                environment_info={},
                test_metadata={"parse_error": str(e)},
                api_url=api_url,
                processed_at=datetime.utcnow().isoformat(),
                raw_response=raw_response
            )
    
    def _extract_failure_stage(self, data: Dict[str, Any]) -> Optional[str]:
        """Extract failure stage from JITA response."""
        # Look for failure stage in common locations
        stage_fields = ["failure_stage", "failed_stage", "stage", "phase"]
        
        for field in stage_fields:
            if field in data and data[field]:
                return str(data[field])
        
        # Try to infer from error messages
        error_message = data.get("error_message", "").lower()
        if "setup" in error_message:
            return "setup"
        elif "teardown" in error_message:
            return "teardown"
        elif "execution" in error_message or "test" in error_message:
            return "execution"
        
        return None
    
    def _extract_failure_step(self, data: Dict[str, Any]) -> Optional[int]:
        """Extract failure step number from JITA response."""
        # Look for explicit failure step
        step_fields = ["failure_step", "failed_step", "error_step"]
        
        for field in step_fields:
            if field in data and isinstance(data[field], (int, str)):
                try:
                    return int(data[field])
                except (ValueError, TypeError):
                    continue
        
        # Try to infer from step logs
        steps = data.get("steps", [])
        if isinstance(steps, list):
            for i, step in enumerate(steps):
                if isinstance(step, dict):
                    status = step.get("status", "").lower()
                    if status in ["failed", "error", "fatal"]:
                        return i
        
        return None
    
    def _parse_exceptions(self, data: Dict[str, Any]) -> List[JITAException]:
        """Parse exception information from JITA response."""
        exceptions = []
        
        # Look for exceptions in various locations
        exception_sources = [
            data.get("exception", {}),
            data.get("error", {}),
            data.get("failure_info", {})
        ]
        
        # Also check step-level exceptions
        steps = data.get("steps", [])
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and step.get("exception"):
                    exception_sources.append(step["exception"])
        
        for exc_data in exception_sources:
            if exc_data and isinstance(exc_data, dict):
                exception = JITAException(
                    exception_type=exc_data.get("type") or exc_data.get("class"),
                    message=exc_data.get("message", ""),
                    traceback=exc_data.get("traceback") or exc_data.get("stack_trace"),
                    stage=exc_data.get("stage"),
                    timestamp=exc_data.get("timestamp")
                )
                
                if exception.message:  # Only add if we have a message
                    exceptions.append(exception)
        
        # Fallback to top-level error message
        if not exceptions:
            error_msg = data.get("error_message")
            if error_msg:
                exceptions.append(JITAException(
                    exception_type=None,
                    message=error_msg,
                    traceback=None,
                    stage=self._extract_failure_stage(data),
                    timestamp=None
                ))
        
        return exceptions
    
    def _parse_step_logs(self, data: Dict[str, Any]) -> List[JITAStepLog]:
        """Parse step logs from JITA response."""
        step_logs = []
        
        # Look for step logs in various locations
        steps = data.get("steps", [])
        if isinstance(steps, list):
            for i, step in enumerate(steps):
                if isinstance(step, dict):
                    log_entry = JITAStepLog(
                        step_number=i,
                        timestamp=step.get("timestamp"),
                        command=step.get("command") or step.get("action"),
                        output=step.get("output", "") or step.get("log", ""),
                        status=step.get("status", "unknown"),
                        duration=step.get("duration_ms") or step.get("duration"),
                        error_level=self._determine_error_level(step)
                    )
                    step_logs.append(log_entry)
        
        # Fallback to flat log entries
        if not step_logs:
            logs = data.get("logs", []) or data.get("output", [])
            if isinstance(logs, list):
                for i, log in enumerate(logs):
                    log_text = str(log) if not isinstance(log, dict) else log.get("message", "")
                    step_logs.append(JITAStepLog(
                        step_number=i,
                        timestamp=None,
                        command=None,
                        output=log_text,
                        status="unknown",
                        duration=None,
                        error_level=self._determine_error_level_from_text(log_text)
                    ))
        
        return step_logs
    
    def _determine_error_level(self, step_data: Dict[str, Any]) -> str:
        """Determine error level from step data."""
        status = step_data.get("status", "").lower()
        
        if status in ["failed", "error", "fatal"]:
            return "error"
        elif status in ["warning", "warn"]:
            return "warning"
        
        # Check output content
        output = step_data.get("output", "").lower()
        return self._determine_error_level_from_text(output)
    
    def _determine_error_level_from_text(self, text: str) -> str:
        """Determine error level from text content."""
        text_lower = text.lower()
        
        if any(keyword in text_lower for keyword in ["error", "failed", "fatal", "exception"]):
            return "error"
        elif any(keyword in text_lower for keyword in ["warning", "warn"]):
            return "warning"
        else:
            return "info"
    
    def _categorize_log_steps(self, step_logs: List[JITAStepLog]) -> Tuple[List[int], List[int]]:
        """Categorize step logs into error and warning steps."""
        error_steps = []
        warning_steps = []
        
        for log in step_logs:
            if log.error_level == "error":
                error_steps.append(log.step_number)
            elif log.error_level == "warning":
                warning_steps.append(log.step_number)
        
        return error_steps, warning_steps
    
    def _extract_environment_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract environment information from JITA response."""
        env_info = {}
        
        # Common environment fields
        env_fields = [
            "cluster_type", "deployment_type", "region", "environment",
            "config", "metadata", "test_config", "setup_config"
        ]
        
        for field in env_fields:
            if field in data:
                env_info[field] = data[field]
        
        # Extract nested environment data
        if "environment" in data and isinstance(data["environment"], dict):
            env_info.update(data["environment"])
        
        return env_info
    
    def _extract_test_metadata(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract test metadata from JITA response."""
        metadata = {}
        
        # Standard metadata fields
        meta_fields = [
            "test_name", "test_suite", "test_type", "priority",
            "tags", "labels", "retry_count", "max_retries"
        ]
        
        for field in meta_fields:
            if field in data:
                metadata[field] = data[field]
        
        return metadata
    
    def _extract_error_keywords(self, step_logs: List[JITAStepLog]) -> List[str]:
        """Extract key error terms from step logs for search query."""
        keywords = set()
        
        # Common error patterns to extract
        error_patterns = [
            r'\b(timeout|connection|refused|unreachable)\b',
            r'\b(failed|error|exception|fatal)\b',
            r'\b(cluster|deployment|resource|memory)\b',
            r'\b(network|ssh|connectivity)\b'
        ]
        
        for log in step_logs:
            if log.error_level == "error":
                text = log.output.lower()
                for pattern in error_patterns:
                    matches = re.findall(pattern, text)
                    keywords.update(matches)
        
        return list(keywords)
    
    def _analyze_basic_logs(self, test_result: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback analysis with basic test result data."""
        return {
            "success": False,
            "source": "fallback_analysis",
            "error_message": test_result.get("error_message", ""),
            "failure_stage": test_result.get("failure_stage", "unknown"),
            "analysis_note": "Limited analysis - JITA API data not available"
        }
    
    def _analyze_detailed_logs(self, jita_result: JITAAnalysisResult) -> Dict[str, Any]:
        """Detailed analysis with full JITA data."""
        analysis = {
            "success": jita_result.success,
            "source": "jita_api",
            "test_status": jita_result.test_status,
            "failure_stage": jita_result.failure_stage,
            "failure_step": jita_result.failure_step,
            "total_steps": len(jita_result.step_logs),
            "error_steps": jita_result.error_steps,
            "warning_steps": jita_result.warning_steps,
            "execution_time_ms": jita_result.execution_time_ms,
            "api_response_time": jita_result.api_response_time
        }
        
        # Add failure timeline
        if jita_result.step_logs:
            timeline = []
            for log in jita_result.step_logs:
                timeline.append({
                    "step": log.step_number,
                    "status": log.status,
                    "error_level": log.error_level,
                    "output_preview": log.output[:100] if log.output else "",
                    "duration": log.duration
                })
            analysis["timeline"] = timeline
        
        # Add exception details
        if jita_result.all_exceptions:
            analysis["exceptions"] = [
                {
                    "type": exc.exception_type,
                    "message": exc.message[:200],
                    "stage": exc.stage,
                    "signature": exc.get_error_signature()
                }
                for exc in jita_result.all_exceptions
            ]
        
        return analysis
    
    def _analyze_basic_exceptions(self, test_result: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback exception analysis."""
        return {
            "success": False,
            "source": "fallback_analysis",
            "error_message": test_result.get("error_message", ""),
            "exception_count": 0,
            "analysis_note": "Limited exception analysis - JITA API data not available"
        }
    
    def _analyze_detailed_exceptions(self, jita_result: JITAAnalysisResult) -> Dict[str, Any]:
        """Detailed exception analysis with full JITA data."""
        analysis = {
            "success": jita_result.success,
            "source": "jita_api",
            "exception_count": len(jita_result.all_exceptions),
            "has_primary_exception": jita_result.primary_exception is not None
        }
        
        if jita_result.primary_exception:
            primary = jita_result.primary_exception
            analysis["primary_exception"] = {
                "type": primary.exception_type,
                "message": primary.message,
                "stage": primary.stage,
                "signature": primary.get_error_signature(),
                "has_traceback": primary.traceback is not None
            }
        
        if jita_result.all_exceptions:
            analysis["exception_summary"] = [
                {
                    "type": exc.exception_type or "Unknown",
                    "message_preview": exc.message[:100],
                    "stage": exc.stage or "unknown"
                }
                for exc in jita_result.all_exceptions
            ]
        
        return analysis
    
    def _get_from_cache(self, key: str) -> Optional[JITAAnalysisResult]:
        """Get result from cache if not expired."""
        if key in self._cache:
            cached_data, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return cached_data
            else:
                # Remove expired entry
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, result: JITAAnalysisResult):
        """Set result in cache with timestamp."""
        self._cache[key] = (result, time.time())
        
        # Simple cache cleanup - remove old entries if cache gets too large
        if len(self._cache) > 100:
            # Remove oldest 20 entries
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1][1])
            for old_key, _ in sorted_items[:20]:
                del self._cache[old_key]


# Utility functions for agent integration

async def get_jita_analysis(test_id: str) -> Optional[JITAAnalysisResult]:
    """
    Convenience function to get JITA analysis for a test ID.
    
    Usage:
        jita_result = await get_jita_analysis(test_result["test_id"])
        if jita_result and jita_result.success:
            # Use JITA analysis data
    """
    service = JITAService()
    return await service.get_test_results(test_id)


async def analyze_test_logs(test_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to analyze test logs.
    
    Usage:
        log_analysis = await analyze_test_logs(test_result)
        failure_stage = log_analysis.get("failure_stage")
    """
    service = JITAService()
    return await service.analyze_step_logs(test_result)


async def extract_test_exceptions(test_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to extract test exceptions.
    
    Usage:
        exception_analysis = await extract_test_exceptions(test_result)
        primary_exception = exception_analysis.get("primary_exception")
    """
    service = JITAService()
    return await service.extract_exception_analysis(test_result)


def build_search_query_from_jita(jita_result: JITAAnalysisResult) -> str:
    """
    Convenience function to build Glean search query from JITA results.
    
    Usage:
        search_query = build_search_query_from_jita(jita_result)
        # Use query with Glean MCP integration
    """
    service = JITAService()
    return service.build_glean_search_query(jita_result)