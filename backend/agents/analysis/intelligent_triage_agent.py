"""
Intelligent Triage Agent for RegX-AI

Implements smart analysis logic based on test history, failure patterns,
and Nutanix knowledge base integration through Glean search.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import json
import requests
import re

from ..base import BaseAgent, AnalysisResult, AgentConfig
from ..services.pattern_cache import PatternCache, PatternMatch
from ..services.cost_tracker import CostTracker
from ..integration.mcp_bridge import MCPBridgeAgent

logger = logging.getLogger(__name__)


@dataclass
class TestHistory:
    """Test execution history for intermittent detection."""
    test_name: str
    last_run_status: str
    recent_runs: List[str]  # Last 5 run statuses
    pass_rate: float
    is_intermittent: bool
    
    @classmethod
    def analyze_intermittent(cls, test_name: str, history_data: List[Dict]) -> "TestHistory":
        """Analyze if test is intermittent based on history."""
        if not history_data:
            return cls(test_name, "unknown", [], 0.0, False)
        
        statuses = [run.get("status", "unknown") for run in history_data[-5:]]
        last_status = statuses[-1] if statuses else "unknown"
        
        pass_count = sum(1 for status in statuses if status == "passed")
        pass_rate = pass_count / len(statuses) if statuses else 0.0
        
        # Intermittent if last run passed but current failed, or mixed results
        is_intermittent = (
            (last_status == "passed") or 
            (0.2 < pass_rate < 0.8 and len(set(statuses)) > 1)
        )
        
        return cls(test_name, last_status, statuses, pass_rate, is_intermittent)


@dataclass
class GleanSearchResult:
    """Result from Glean knowledge search."""
    found_existing_issue: bool
    confidence: float
    knowledge_summary: str
    suggested_tickets: List[str]
    related_docs: List[str]
    nutanix_knowledge: Dict[str, Any]


@dataclass
class JITAAnalysisResult:
    """Result from JITA API analysis."""
    success: bool
    failure_stage: str
    exception_analysis: str
    step_logs: List[str]
    root_cause: Optional[str]
    api_url: str


class IntelligentTriageAgent(BaseAgent):
    """
    Intelligent Triage Agent with enhanced analysis logic.
    
    Implements:
    1. History-based intermittent detection
    2. First Level AI Analysis (JITA + Glean)
    3. Pattern learning and enhancement
    4. Existing issue detection and ticket suggestions
    """
    
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        
        # Initialize services
        self.pattern_cache = PatternCache()
        self.cost_tracker = CostTracker()
        
        # MCP bridge for Glean search
        self.mcp_bridge = None
        
        # JITA API configuration
        self.jita_base_url = "https://jita-phx1-webserver-2.eng.nutanix.com/api/v2"
        
        # Analysis thresholds
        self.intermittent_threshold = 0.7  # Pass rate below this = intermittent
        self.confidence_threshold = 0.8
        self.auto_triage_threshold = 0.9  # Pattern confidence for auto-triage
        
        # Load separate pattern databases
        self.intermittent_patterns = self._load_intermittent_patterns()
        self.rdm_patterns = self._load_rdm_patterns()
        
        self.logger.info(f"Intelligent Triage Agent initialized with {len(self.intermittent_patterns)} intermittent patterns and {len(self.rdm_patterns)} RDM patterns")
    
    def _load_intermittent_patterns(self) -> List[Dict[str, Any]]:
        """Load intermittent patterns for setup stage failures."""
        try:
            with open("/Users/sudharshan.musali/regx/RegX-AI/backend/intermittent_patterns.json", 'r') as f:
                data = json.load(f)
                patterns = data.get("intermittent_patterns", [])
                self.logger.info(f"Loaded {len(patterns)} intermittent patterns")
                return patterns
        except Exception as e:
            self.logger.error(f"Failed to load intermittent patterns: {e}")
            return []
    
    def _load_rdm_patterns(self) -> List[Dict[str, Any]]:
        """Load RDM patterns for skipped test failures."""
        try:
            with open("/Users/sudharshan.musali/regx/RegX-AI/data/rdm_failure_patterns.json", 'r') as f:
                data = json.load(f)
                patterns = data.get("failure_patterns", [])
                self.logger.info(f"Loaded {len(patterns)} RDM failure patterns")
                return patterns
        except Exception as e:
            self.logger.error(f"Failed to load RDM patterns: {e}")
            return []
    
    def set_mcp_bridge(self, mcp_bridge: MCPBridgeAgent):
        """Set MCP bridge for Glean search integration."""
        self.mcp_bridge = mcp_bridge
    
    async def analyze(self, test_result: Dict[str, Any], user_requested_ai: bool = False) -> AnalysisResult:
        """
        Perform intelligent analysis based on test status and history.
        
        Analysis flow:
        1. Determine test status (failed/skipped)
        2. Check test history for intermittent patterns
        3. Apply appropriate analysis logic
        4. Enhance patterns with results
        """
        start_time = time.time()
        
        try:
            test_status = test_result.get("status", "").lower()
            test_name = test_result.get("test_name", "")
            
            self.logger.info(f"Analyzing {test_status} test: {test_name}")
            
            if test_status in ("failed", "failure"):
                result = await self._analyze_failed_test(test_result, user_requested_ai)
            elif test_status == "skipped":
                result = await self._analyze_skipped_test(test_result, user_requested_ai)
            else:
                result = AnalysisResult(
                    success=False,
                    analysis_type="unsupported_status",
                    confidence=0.0,
                    pattern_matched=False,
                    pattern_description=f"Unsupported test status: {test_status}",
                    source="error"
                )
            
            # Set execution time
            result.execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Track usage for analytics (not limiting)
            self._track_analysis_usage(result, test_result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Analysis failed: {e}")
            execution_time = int((time.time() - start_time) * 1000)
            
            return AnalysisResult(
                success=False,
                analysis_type="analysis_error",
                confidence=0.0,
                pattern_matched=False,
                execution_time_ms=execution_time,
                source="error",
                errors=[str(e)]
            )
    
    async def _analyze_failed_test(self, test_result: Dict[str, Any], user_requested_ai: bool = False) -> AnalysisResult:
        """
        Enhanced failed test analysis with refined trigger conditions.
        
        Logic:
        1. Detect failure type (setup, test body, other)
        2. Auto-trigger First Level AI for:
           - Class/Test setup failures
           - Test body failures where previous run passed (same branch)
        3. Show Deep AI button for other failure types
        """
        test_name = test_result.get("test_name", "")
        
        # Check if user requested deep AI analysis
        if user_requested_ai:
            return await self._first_level_ai_analysis(test_result, "user_requested_deep_ai")
        
        # Step 1: Detect failure type
        failure_type = self._detect_failure_type(test_result)
        
        # Step 2: Determine analysis approach based on failure type
        if failure_type == "setup_failure":
            # Auto-trigger First Level AI for setup failures
            return await self._first_level_ai_analysis(test_result, "auto_setup_failure")
            
        elif failure_type == "test_body_failure":
            # Check for intermittent pattern (previous passed, current failed)
            if await self._check_intermittent_pattern(test_result):
                # Auto-trigger First Level AI for intermittent test body failures
                return await self._first_level_ai_analysis(test_result, "auto_intermittent_failure")
            else:
                # Show Deep AI button for other test body failures
                return self._create_deep_ai_button_result(test_result, "test_body")
        
        else:
            # For other failure types, try pattern matching first
            pattern_match = self.pattern_cache.find_best_pattern_match(test_result)
            if pattern_match and pattern_match.confidence >= self.confidence_threshold:
                return AnalysisResult(
                    success=True,
                    analysis_type="pattern_match",
                    confidence=pattern_match.confidence,
                    pattern_matched=True,
                    pattern_description=pattern_match.description,
                    rdm_category=pattern_match.category,
                    source="pattern_cache",
                    data={"pattern_id": getattr(pattern_match, 'pattern_id', 'unknown')}
                )
            
            # Show Deep AI button for unmatched other failures
            return self._create_deep_ai_button_result(test_result, "other_failure")
    
    async def _analyze_skipped_test(self, test_result: Dict[str, Any], user_requested_ai: bool = False) -> AnalysisResult:
        """
        Enhanced skipped test analysis with RDM pattern matching.
        
        Logic:
        1. Check if user requested deep AI analysis
        2. Use RDM failure patterns for pattern matching
        3. Show First Level AI button for non-matching cases
        """
        # Check if user requested deep AI analysis
        if user_requested_ai:
            return await self._first_level_ai_analysis(test_result, "user_requested_deep_ai")
        
        # Step 1: Use RDM failure patterns
        pattern_match = self._match_rdm_patterns(test_result)
        if pattern_match:
            return self._create_auto_triage_result(pattern_match, "rdm")
        
        # Step 2: No pattern matched - show First Level AI button
        return self._create_manual_analysis_result(test_result, "skipped")
    
    async def _first_level_ai_analysis(
        self, 
        test_result: Dict[str, Any], 
        analysis_reason: str
    ) -> AnalysisResult:
        """
        Perform First Level AI Analysis using JITA API + Glean search.
        
        Steps:
        1. Get failure details from JITA API
        2. Analyze exception and step logs
        3. Perform Glean search for existing issues
        4. Generate comprehensive analysis
        """
        self.logger.info(f"Starting First Level AI Analysis for {analysis_reason}")
        
        # Step 1: JITA API Analysis
        jita_result = await self._analyze_with_jita_api(test_result)
        
        # Step 2: Prepare search query for Glean
        search_query = self._build_glean_search_query(test_result, jita_result)
        
        # Step 3: Glean search for existing issues
        glean_result = await self._glean_search_existing_issues(search_query, test_result)
        
        # Step 4: Combine results
        confidence = 0.8 if glean_result.found_existing_issue else 0.6
        
        analysis_data = {
            "analysis_reason": analysis_reason,
            "jita_analysis": jita_result.__dict__,
            "glean_search": glean_result.__dict__,
            "first_level_ai": True,
            "existing_issue_found": glean_result.found_existing_issue,
            "suggested_tickets": glean_result.suggested_tickets,
            "nutanix_knowledge": glean_result.nutanix_knowledge,
            "failure_understanding": self._generate_failure_understanding(
                test_result, jita_result, glean_result
            )
        }
        
        return AnalysisResult(
            success=True,
            analysis_type="first_level_ai_analysis",
            confidence=confidence,
            pattern_matched=False,
            pattern_description=glean_result.knowledge_summary,
            rdm_category=self._determine_category_from_analysis(jita_result, glean_result),
            source="first_level_ai",
            data=analysis_data
        )
    
    async def _get_test_history(self, test_name: str) -> TestHistory:
        """Get test execution history for intermittent detection."""
        try:
            # This would integrate with actual test history API
            # For now, simulate history analysis
            
            # Mock history data - in production, fetch from actual test database
            mock_history = [
                {"status": "passed", "timestamp": time.time() - 86400},
                {"status": "failed", "timestamp": time.time() - 172800},
                {"status": "passed", "timestamp": time.time() - 259200},
                {"status": "passed", "timestamp": time.time() - 345600},
            ]
            
            return TestHistory.analyze_intermittent(test_name, mock_history)
            
        except Exception as e:
            self.logger.warning(f"Failed to get test history: {e}")
            return TestHistory(test_name, "unknown", [], 0.0, False)
    
    async def _analyze_with_jita_api(self, test_result: Dict[str, Any]) -> JITAAnalysisResult:
        """
        Analyze test failure using JITA API.
        
        Calls: https://jita-phx1-webserver-2.eng.nutanix.com/api/v2/agave_test_results/{test_id}
        """
        try:
            task_id = test_result.get("task_id")
            if not task_id:
                return JITAAnalysisResult(
                    success=False,
                    failure_stage="unknown",
                    exception_analysis="No task ID available",
                    step_logs=[],
                    root_cause=None,
                    api_url=""
                )
            
            # Call JITA API
            api_url = f"{self.jita_base_url}/agave_test_results/{task_id}"
            
            # Mock API call - in production, make actual HTTP request
            # response = requests.get(api_url, timeout=30)
            
            # Simulate JITA analysis
            failure_stage = self._detect_failure_stage(test_result)
            exception_analysis = self._analyze_exception_summary(test_result)
            
            return JITAAnalysisResult(
                success=True,
                failure_stage=failure_stage,
                exception_analysis=exception_analysis,
                step_logs=["Step 1: Setup", "Step 2: Execution", "Step 3: Cleanup"],
                root_cause=self._infer_root_cause(test_result),
                api_url=api_url
            )
            
        except Exception as e:
            self.logger.error(f"JITA API analysis failed: {e}")
            return JITAAnalysisResult(
                success=False,
                failure_stage="api_error",
                exception_analysis=str(e),
                step_logs=[],
                root_cause=None,
                api_url=""
            )
    
    def _detect_failure_stage(self, test_result: Dict[str, Any]) -> str:
        """Detect the stage where test failed."""
        failure_stage = test_result.get("failure_stage", "")
        if failure_stage:
            return failure_stage
        
        # Analyze error message to determine stage
        error_message = test_result.get("error_message", "").lower()
        
        if "setup" in error_message or "initialization" in error_message:
            return "setup_stage"
        elif "teardown" in error_message or "cleanup" in error_message:
            return "cleanup_stage"
        elif "timeout" in error_message:
            return "execution_timeout"
        elif "connection" in error_message:
            return "connection_failure"
        else:
            return "execution_stage"
    
    def _analyze_exception_summary(self, test_result: Dict[str, Any]) -> str:
        """Analyze exception summary for insights."""
        exception_summary = test_result.get("exception_summary", "")
        error_message = test_result.get("error_message", "")
        
        combined_text = f"{exception_summary} {error_message}"
        
        # Basic analysis - in production, use more sophisticated NLP
        if "timeout" in combined_text.lower():
            return "Timeout related failure - possible performance or connectivity issue"
        elif "connection refused" in combined_text.lower():
            return "Service connectivity failure - check service availability"
        elif "authentication" in combined_text.lower():
            return "Authentication failure - check credentials and permissions"
        elif "not found" in combined_text.lower():
            return "Resource not found - check resource availability and configuration"
        else:
            return f"Exception analysis: {exception_summary[:200]}"
    
    def _infer_root_cause(self, test_result: Dict[str, Any]) -> Optional[str]:
        """Infer root cause from available data."""
        failure_stage = self._detect_failure_stage(test_result)
        
        if failure_stage == "setup_stage":
            return "Environment setup or configuration issue"
        elif failure_stage == "connection_failure":
            return "Network or service connectivity issue"
        elif failure_stage == "execution_timeout":
            return "Performance or resource availability issue"
        else:
            return None
    
    def _build_glean_search_query(
        self, 
        test_result: Dict[str, Any], 
        jita_result: JITAAnalysisResult
    ) -> str:
        """Build optimized search query for Glean."""
        components = []
        
        # Add test name context
        test_name = test_result.get("test_name", "")
        if test_name:
            # Extract meaningful parts of test name
            test_parts = test_name.replace(".", " ").replace("_", " ").split()
            components.extend(test_parts[-3:])  # Last 3 parts usually most relevant
        
        # Add exception keywords
        exception_summary = test_result.get("exception_summary", "")
        if exception_summary:
            # Extract key error terms
            error_keywords = self._extract_error_keywords(exception_summary)
            components.extend(error_keywords[:5])
        
        # Add failure stage
        if jita_result.success and jita_result.failure_stage:
            components.append(jita_result.failure_stage.replace("_", " "))
        
        # Add root cause if available
        if jita_result.root_cause:
            components.append(jita_result.root_cause)
        
        # Build query
        query = " ".join(components[:10])  # Limit to 10 terms
        return query.strip()
    
    def _extract_error_keywords(self, error_text: str) -> List[str]:
        """Extract meaningful keywords from error text."""
        # Common error keywords to prioritize
        important_terms = [
            "timeout", "connection", "refused", "authentication", "permission",
            "not found", "invalid", "failed", "error", "exception", "unable"
        ]
        
        words = error_text.lower().split()
        keywords = []
        
        # Add important terms first
        for word in words:
            if any(term in word for term in important_terms):
                keywords.append(word)
        
        # Add other significant words (longer than 4 chars, not common words)
        common_words = {"the", "and", "for", "with", "from", "this", "that", "have", "will"}
        for word in words:
            if len(word) > 4 and word not in common_words and word not in keywords:
                keywords.append(word)
        
        return keywords[:10]
    
    async def _glean_search_existing_issues(
        self, 
        search_query: str, 
        test_result: Dict[str, Any]
    ) -> GleanSearchResult:
        """
        Search Glean for existing issues and Nutanix knowledge.
        
        Glean provides Nutanix product knowledge and analysis for failures.
        """
        try:
            if not self.mcp_bridge:
                return GleanSearchResult(
                    found_existing_issue=False,
                    confidence=0.0,
                    knowledge_summary="MCP bridge not available",
                    suggested_tickets=[],
                    related_docs=[],
                    nutanix_knowledge={}
                )
            
            # Call Glean search via MCP
            mcp_result = await self.mcp_bridge.call_mcp_tool(
                server_id="gw-glean",
                tool_name="search",
                arguments={
                    "query": search_query,
                    "mode": "nutanix_knowledge",
                    "include_tickets": True
                },
                user_requested=True  # Always allow Glean search
            )
            
            if mcp_result.success:
                return self._process_glean_results(mcp_result.response_data, search_query)
            else:
                return GleanSearchResult(
                    found_existing_issue=False,
                    confidence=0.0,
                    knowledge_summary="Glean search failed",
                    suggested_tickets=[],
                    related_docs=[],
                    nutanix_knowledge={"error": mcp_result.error}
                )
                
        except Exception as e:
            self.logger.error(f"Glean search failed: {e}")
            return GleanSearchResult(
                found_existing_issue=False,
                confidence=0.0,
                knowledge_summary=f"Search error: {str(e)}",
                suggested_tickets=[],
                related_docs=[],
                nutanix_knowledge={}
            )
    
    def _process_glean_results(self, glean_data: Dict[str, Any], query: str) -> GleanSearchResult:
        """Process Glean search results."""
        try:
            # Extract results from Glean response
            results = glean_data.get("results", [])
            
            if not results:
                return GleanSearchResult(
                    found_existing_issue=False,
                    confidence=0.0,
                    knowledge_summary="No relevant Nutanix knowledge found",
                    suggested_tickets=[],
                    related_docs=[],
                    nutanix_knowledge={}
                )
            
            # Process results
            tickets = []
            docs = []
            knowledge_summary = ""
            
            for result in results[:5]:  # Top 5 results
                title = result.get("title", "")
                url = result.get("url", "")
                snippet = result.get("snippet", "")
                
                if "jira" in url.lower() or "ticket" in title.lower():
                    tickets.append(url)
                elif "doc" in url.lower() or "wiki" in url.lower():
                    docs.append(url)
                
                if not knowledge_summary and snippet:
                    knowledge_summary = snippet[:200]
            
            # Determine if existing issue found
            found_existing = len(tickets) > 0 or any(
                keyword in knowledge_summary.lower() 
                for keyword in ["known issue", "workaround", "fix available"]
            )
            
            confidence = 0.8 if found_existing else 0.5
            
            return GleanSearchResult(
                found_existing_issue=found_existing,
                confidence=confidence,
                knowledge_summary=knowledge_summary or "Nutanix knowledge search completed",
                suggested_tickets=tickets,
                related_docs=docs,
                nutanix_knowledge={
                    "query": query,
                    "total_results": len(results),
                    "processed_results": len(results[:5])
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to process Glean results: {e}")
            return GleanSearchResult(
                found_existing_issue=False,
                confidence=0.0,
                knowledge_summary=f"Processing error: {str(e)}",
                suggested_tickets=[],
                related_docs=[],
                nutanix_knowledge={}
            )
    
    def _generate_failure_understanding(
        self, 
        test_result: Dict[str, Any],
        jita_result: JITAAnalysisResult,
        glean_result: GleanSearchResult
    ) -> str:
        """Generate human-readable failure understanding."""
        components = []
        
        # Test context
        test_name = test_result.get("test_name", "Unknown test")
        components.append(f"Test: {test_name}")
        
        # Failure stage and analysis
        if jita_result.success:
            components.append(f"Failed at: {jita_result.failure_stage}")
            if jita_result.root_cause:
                components.append(f"Root cause: {jita_result.root_cause}")
        
        # Glean insights
        if glean_result.found_existing_issue:
            components.append("Existing issue found in Nutanix knowledge base")
            if glean_result.suggested_tickets:
                components.append(f"Related tickets: {len(glean_result.suggested_tickets)}")
        
        # Exception analysis
        if jita_result.exception_analysis:
            components.append(f"Analysis: {jita_result.exception_analysis}")
        
        return ". ".join(components)
    
    def _determine_category_from_analysis(
        self, 
        jita_result: JITAAnalysisResult,
        glean_result: GleanSearchResult
    ) -> str:
        """Determine RDM category based on analysis results."""
        if jita_result.failure_stage in ("setup_stage", "connection_failure"):
            return "INFRASTRUCTURE"
        elif glean_result.found_existing_issue:
            return "PRODUCT"  # Known product issue
        elif "timeout" in jita_result.exception_analysis.lower():
            return "TEST_BUG"  # Likely test timing issue
        else:
            return "PRODUCT"  # Default to product issue
    
    def _track_analysis_usage(self, result: AnalysisResult, test_result: Dict[str, Any]):
        """Track analysis usage for analytics (not limiting)."""
        # Determine cost based on analysis type
        credits_used = 0
        
        if result.analysis_type == "pattern_match":
            credits_used = 0  # Pattern matching is free
        elif result.analysis_type == "first_level_ai_analysis":
            credits_used = 15  # First level AI analysis cost
        elif result.analysis_type == "rdm_pattern_with_glean":
            credits_used = 5   # Pattern + Glean search
        
        result.credits_used = credits_used
        
        # Track for analytics
        self.cost_tracker.track_usage(
            analysis_type=result.analysis_type,
            credits_used=credits_used,
            agent_name=self.config.name,
            success=result.success,
            metadata={
                "test_name": test_result.get("test_name", ""),
                "status": test_result.get("status", ""),
                "confidence": result.confidence,
                "pattern_matched": result.pattern_matched,
                "existing_issue_found": result.data.get("existing_issue_found", False)
            },
            bypass_limits=True  # Always bypass limits - this is for analytics only
        )
    
    def _is_setup_stage_failure(self, test_result: Dict[str, Any]) -> bool:
        """Detect if this is a setup stage failure."""
        error_message = test_result.get("error_message", "").lower()
        failure_stage = test_result.get("failure_stage", "").lower()
        
        setup_indicators = [
            "setup", "initialization", "cluster start", "environment", 
            "configuration", "deployment", "timeout executing command source"
        ]
        
        return (
            failure_stage in ("setup", "initialization") or
            any(indicator in error_message for indicator in setup_indicators)
        )
    
    def _detect_failure_type(self, test_result: Dict[str, Any]) -> str:
        """Detect the specific type of test failure."""
        error_message = test_result.get("error_message", "").lower()
        failure_stage = test_result.get("failure_stage", "").lower()
        
        # Check for setup failures (class setup, test setup)
        setup_indicators = [
            "class setup", "test setup", "setup_class", "setup_method",
            "classsetup", "testsetup", "setupclass", "setupmethod",
            "beforeclass", "before_class", "setup()"
        ]
        
        if any(indicator in error_message or indicator in failure_stage 
               for indicator in setup_indicators):
            return "setup_failure"
        
        # Check for test body failures
        test_body_indicators = [
            "test_execution", "test_body", "test body", "test method",
            "testmethod", "test_case", "testcase", "test execution"
        ]
        
        if (failure_stage in test_body_indicators or 
            any(indicator in error_message for indicator in test_body_indicators)):
            return "test_body_failure"
        
        # Default to other failure type
        return "other_failure"
    
    async def _check_intermittent_pattern(self, test_result: Dict[str, Any]) -> bool:
        """Check if test shows intermittent pattern (previous passed, current failed)."""
        test_name = test_result.get("test_name")
        branch = test_result.get("system_under_test", {}).get("branch", "main")
        current_test_id = test_result.get("_id", {}).get("$oid", "")
        
        if not test_name:
            return False
        
        try:
            from ...services.jita_history_service import check_previous_run_success
            
            # Check if previous run was successful using JITA History API
            previous_success = await check_previous_run_success(
                test_name=test_name,
                branch=branch,
                current_test_id=current_test_id
            )
            
            current_status = test_result.get("status", "").lower()
            
            # Intermittent pattern: previous run passed, current run failed
            is_intermittent = (previous_success and current_status in ("failed", "failure"))
            
            self.logger.info(
                f"Intermittent check for {test_name}: "
                f"Previous={'Success' if previous_success else 'Failed'}, "
                f"Current={current_status}, Intermittent={is_intermittent}"
            )
            
            return is_intermittent
            
        except Exception as e:
            self.logger.error(f"Error checking intermittent pattern: {str(e)}")
            return False
    
    async def _get_test_history_for_branch(self, test_name: str, branch: str) -> Optional[TestHistory]:
        """Get test execution history for a specific branch using JITA History API."""
        try:
            from ...services.jita_history_service import JITAHistoryService
            
            # Use JITA History service to get test execution history
            jita_service = JITAHistoryService()
            jita_history = await jita_service.get_test_execution_history(
                test_name=test_name,
                branch=branch,
                limit=10,
                official_only=True
            )
            
            if jita_history:
                # Convert JITA history to internal format for TestHistory analysis
                history_data = [
                    {
                        "status": "passed" if run.is_successful else "failed",
                        "executed_at": run.start_time,
                        "test_id": run.test_id,
                        "gbn": run.gbn
                    }
                    for run in jita_history
                ]
                
                self.logger.info(
                    f"Retrieved {len(history_data)} history entries for {test_name} on {branch}"
                )
                
                return TestHistory.analyze_intermittent(test_name, history_data)
            else:
                # No history available
                self.logger.warning(f"No JITA history found for {test_name} on {branch}")
                return TestHistory(test_name, "unknown", [], 0.0, False)
                
        except Exception as e:
            self.logger.error(f"Error getting test history for {test_name} on {branch}: {str(e)}")
            return TestHistory(test_name, "unknown", [], 0.0, False)
    
    def _create_deep_ai_button_result(self, test_result: Dict[str, Any], failure_type: str) -> AnalysisResult:
        """Create result that shows Deep AI Analysis button."""
        return AnalysisResult(
            success=False,
            analysis_type=f"deep_ai_required_{failure_type}",
            confidence=0.3,
            pattern_matched=False,
            pattern_description="No automatic pattern match - Deep AI analysis available",
            source="intelligent_triage",
            data={
                "requires_deep_ai_analysis": True,
                "failure_type": failure_type,
                "auto_analysis": False,
                "user_action_required": "Click Deep AI Analysis button for detailed analysis"
            }
        )
    
    def _match_intermittent_patterns(self, test_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Match test result against intermittent patterns."""
        error_message = test_result.get("error_message", "")
        
        for pattern in self.intermittent_patterns:
            if self._pattern_matches(pattern, error_message, test_result):
                confidence = pattern.get("confidence", 0.8)
                if confidence >= self.auto_triage_threshold:
                    return pattern
        
        return None
    
    def _match_rdm_patterns(self, test_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Match test result against RDM failure patterns."""
        error_message = test_result.get("error_message", "")
        skip_reason = test_result.get("skip_reason", "")
        
        for pattern in self.rdm_patterns:
            if self._pattern_matches(pattern, f"{error_message} {skip_reason}", test_result):
                confidence = pattern.get("confidence", 0.8)
                if confidence >= self.auto_triage_threshold:
                    return pattern
        
        return None
    
    def _pattern_matches(self, pattern: Dict[str, Any], text: str, test_result: Dict[str, Any]) -> bool:
        """Check if pattern matches the given text."""
        import re
        
        regex = pattern.get("regex", "")
        if not regex:
            return False
        
        try:
            return bool(re.search(regex, text, re.IGNORECASE))
        except re.error:
            self.logger.error(f"Invalid regex pattern: {regex}")
            return False
    
    def _create_auto_triage_result(self, pattern: Dict[str, Any], pattern_type: str) -> AnalysisResult:
        """Create auto-triage result for high-confidence pattern matches."""
        confidence = pattern.get("confidence", 0.9)
        category = pattern.get("category", pattern_type.upper())
        description = pattern.get("description", f"{pattern_type} pattern detected")
        
        return AnalysisResult(
            success=True,
            analysis_type=f"auto_triage_{pattern_type}",
            confidence=confidence,
            pattern_matched=True,
            pattern_description=description,
            rdm_category=category,
            source="intelligent_triage_auto",
            data={
                "pattern_id": pattern.get("id", "unknown"),
                "pattern_type": pattern_type,
                "auto_triaged": True
            }
        )
    
    def _create_manual_analysis_result(self, test_result: Dict[str, Any], test_type: str) -> AnalysisResult:
        """Create result indicating manual First Level AI analysis is needed."""
        return AnalysisResult(
            success=False,
            analysis_type=f"manual_analysis_required_{test_type}",
            confidence=0.3,
            pattern_matched=False,
            pattern_description="No automatic pattern match found",
            source="intelligent_triage",
            data={
                "requires_manual_analysis": True,
                "test_type": test_type,
                "first_level_ai_available": True
            }
        )
    
    async def process_rdm_fix_approval(
        self, 
        test_result: Dict[str, Any],
        rdm_analysis: Dict[str, Any],
        user_approved: bool = True
    ) -> Dict[str, Any]:
        """
        Process RDM fix approval and auto-disable problematic nodes.
        
        Args:
            test_result: Original test result data
            rdm_analysis: RDM failure analysis results
            user_approved: Whether user approved the RDM fix suggestion
            
        Returns:
            Dictionary with processing results
        """
        try:
            if not user_approved:
                return {
                    "success": False,
                    "message": "User did not approve RDM fix suggestion",
                    "action": "none"
                }
            
            from ...services.jarvis_service import JarvisNodeService, extract_node_from_rdm
            
            # Extract problematic node from RDM analysis
            node_name = extract_node_from_rdm(rdm_analysis)
            if not node_name:
                return {
                    "success": False,
                    "message": "Could not extract node name from RDM analysis",
                    "action": "manual_intervention_required"
                }
            
            self.logger.info(f"Processing RDM fix approval for node: {node_name}")
            
            # Initialize JARVIS service
            jarvis_service = JarvisNodeService()
            
            # Extract RDM link from analysis if available
            rdm_link = self._extract_rdm_link_from_analysis(rdm_analysis)
            
            # Disable the problematic node
            disable_result = await jarvis_service.disable_node(
                node_name=node_name,
                rdm_link=rdm_link,
                reason=f"Auto-disabled due to RDM failure: {rdm_analysis.get('root_cause', 'Node failure detected')}",
                disabled_by=rdm_analysis.get("disabled_by") or "",
            )
            
            result = {
                "node_name": node_name,
                "disable_result": disable_result,
                "action": "node_disabled" if disable_result.get("success") else "disable_failed"
            }
            
            # If node disable was successful, auto-retrigger the test
            if disable_result.get("success"):
                retrigger_result = await jarvis_service.auto_retrigger_testcase(
                    original_test_result=test_result,
                    retrigger_reason=f"Auto-retrigger after disabling problematic node {node_name}"
                )
                
                result.update({
                    "retrigger_result": retrigger_result.to_dict(),
                    "action": "node_disabled_and_retriggered" if retrigger_result.success else "node_disabled_retrigger_failed",
                    "success": retrigger_result.success,
                    "message": f"Node {node_name} disabled and test {'retriggered' if retrigger_result.success else 'retrigger failed'}"
                })
            else:
                result.update({
                    "success": False,
                    "message": f"Failed to disable node {node_name}: {disable_result.get('error', 'Unknown error')}"
                })
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error processing RDM fix approval: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "Exception occurred during RDM fix processing"
            }
    
    def _extract_rdm_link_from_analysis(self, rdm_analysis: Dict[str, Any]) -> Optional[str]:
        """Extract RDM deployment link from analysis results."""
        try:
            # Look for RDM deployment links in various places
            rdm_patterns = [
                r'https://rdm\.eng\.nutanix\.com/scheduled_deployments/([a-fA-F0-9]+)',
                r'rdm\.eng\.nutanix\.com/scheduled_deployments/([a-fA-F0-9]+)',
                r'deployment[_\s]*id[_\s]*:?\s*([a-fA-F0-9]+)',
                r'rdm[_\s]*link[_\s]*:?\s*(https://[^\s]+)'
            ]
            
            # Search in various text fields
            search_texts = [
                rdm_analysis.get("deployment_link", ""),
                rdm_analysis.get("rdm_url", ""),
                rdm_analysis.get("analysis_summary", ""),
                rdm_analysis.get("error_message", ""),
                str(rdm_analysis.get("logs", "")),
                str(rdm_analysis.get("metadata", {}))
            ]
            
            for text in search_texts:
                if not text:
                    continue
                    
                for pattern in rdm_patterns:
                    matches = re.findall(pattern, str(text), re.IGNORECASE)
                    if matches:
                        match = matches[0]
                        # Construct full URL if only deployment ID found
                        if match.startswith('http'):
                            return match
                        else:
                            return f"https://rdm.eng.nutanix.com/scheduled_deployments/{match}"
            
            # Look in structured data
            if "deployment_info" in rdm_analysis:
                dep_info = rdm_analysis["deployment_info"]
                if isinstance(dep_info, dict):
                    dep_id = dep_info.get("deployment_id") or dep_info.get("id")
                    if dep_id:
                        return f"https://rdm.eng.nutanix.com/scheduled_deployments/{dep_id}"
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error extracting RDM link from analysis: {str(e)}")
            return None
    
    def can_handle(self, test_result: Dict[str, Any]) -> bool:
        """Check if this agent can handle the test result."""
        status = test_result.get("status", "").lower()
        return status in ("failed", "failure", "skipped")
    
    def get_agent_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities information."""
        return {
            "name": self.config.name,
            "type": "intelligent_triage",
            "capabilities": [
                "History-based intermittent detection",
                "First Level AI Analysis (JITA + Glean)",
                "Pattern learning and enhancement", 
                "Existing issue detection",
                "Nutanix knowledge base integration"
            ],
            "supported_analysis_types": [
                "Failed testcase analysis",
                "Skipped testcase analysis", 
                "Intermittent failure detection",
                "RDM pattern matching",
                "Glean knowledge search"
            ],
            "integrations": [
                "JITA API for failure analysis",
                "Glean search for Nutanix knowledge",
                "Pattern cache for known issues",
                "Cost tracking for analytics"
            ]
        }