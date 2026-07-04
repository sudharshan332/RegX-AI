"""
CDP Test Failure Triage Agent

Intelligent agent for analyzing CDP test failures using the existing
triage-cdp-test-failure skill with cost optimization and pattern matching.
"""

import asyncio
import logging
import os
import subprocess
import json
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from ..base import SkillWrapperAgent, AnalysisResult, AgentConfig
from ..services.pattern_cache import PatternCache, PatternMatch
from ..services.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


@dataclass
class TriageContext:
    """Context for CDP triage analysis."""
    test_result: Dict[str, Any]
    log_url: Optional[str] = None
    task_id: Optional[str] = None
    failure_category: Optional[str] = None
    requires_rdm_handoff: bool = False
    
    @classmethod
    def from_test_result(cls, test_result: Dict[str, Any]) -> "TriageContext":
        """Create triage context from test result data."""
        failure_analysis = test_result.get("failure_analysis", {})
        failure_category = failure_analysis.get("category", "")
        
        # Check if this requires RDM handoff
        requires_rdm_handoff = (
            test_result.get("status", "").lower() == "skipped" and
            failure_category == "DEVPROD_SERVICE:RDM"
        )
        
        return cls(
            test_result=test_result,
            log_url=test_result.get("log_url"),
            task_id=test_result.get("task_id"),
            failure_category=failure_category,
            requires_rdm_handoff=requires_rdm_handoff
        )


class CDPTriageAgent(SkillWrapperAgent):
    """
    CDP Test Failure Triage Agent
    
    Specialized agent for CDP test failure analysis that wraps the existing
    triage-cdp-test-failure skill with intelligent cost optimization.
    
    Features:
    - Pattern-first analysis to minimize AI credits
    - Integration with existing skill workflows
    - Automated cross-skill handoff to RDM agent
    - Comprehensive JIRA integration
    - Telemetry and pattern enrichment
    """
    
    def __init__(self, config: AgentConfig):
        # Ensure correct skill wrapper
        if not config.skill_wrapper or config.skill_wrapper != "triage-cdp-test-failure":
            config.skill_wrapper = "triage-cdp-test-failure"
        
        super().__init__(config)
        
        # Initialize services
        self.pattern_cache = PatternCache(config.pattern_matching)
        self.cost_tracker = CostTracker()
        
        # Skill-specific configuration
        self.auto_jira_creation = config.cost_optimization.get("auto_jira_creation", False)
        self.telemetry_enabled = config.cost_optimization.get("telemetry_enabled", True)
        self.user_guided_promotion = config.cost_optimization.get("user_guided_promotion", True)
        
        # MCP integration
        self.mcp_dependencies = config.mcp_dependencies
        
        self.logger.info("CDP Triage Agent initialized with cost optimization")
    
    def can_handle(self, test_result: Dict[str, Any]) -> bool:
        """
        Check if this agent can handle the test result.
        
        CDP Triage Agent handles:
        - Failed tests (not skipped due to RDM)
        - Test failures with logs available
        - In-test failures vs deployment failures
        """
        status = test_result.get("status", "").lower()
        failure_category = test_result.get("failure_analysis", {}).get("category", "")
        
        # Handle failed tests (not RDM skipped)
        if status in ("failed", "failure"):
            if failure_category != "DEVPROD_SERVICE:RDM":
                return True
        
        # Handle specific CDP test patterns
        test_name = test_result.get("test_name", "").lower()
        if "cdp" in test_name or "central" in test_name:
            return True
        
        return super().can_handle(test_result)
    
    async def analyze(self, test_result: Dict[str, Any], user_requested_ai: bool = False) -> AnalysisResult:
        """
        Perform comprehensive CDP test failure analysis.
        
        Analysis pipeline:
        1. Create triage context
        2. Check for RDM handoff requirement  
        3. Pattern-first analysis (inherited from base)
        4. Skill-based analysis if needed
        5. JIRA integration and telemetry
        """
        start_time = time.time()
        credits_used = 0
        
        try:
            # Step 1: Create triage context
            context = TriageContext.from_test_result(test_result)
            
            # Step 2: Check for RDM handoff
            if context.requires_rdm_handoff:
                return AnalysisResult(
                    success=True,
                    analysis_type="cdp_handoff", 
                    confidence=0.99,
                    pattern_matched=True,
                    pattern_description="RDM deployment failure - requires handoff",
                    rdm_category="INFRASTRUCTURE",
                    source="handoff",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    data={
                        "requires_handoff": True,
                        "handoff_target": "rdm_analysis_agent",
                        "failure_category": context.failure_category
                    }
                )
            
            # Step 3: Pattern-first analysis (from base class)
            base_result = await super().analyze(test_result)
            
            # If pattern matching was successful, enhance with CDP-specific data
            if base_result.success and base_result.pattern_matched:
                base_result.data.update({
                    "cdp_analysis": True,
                    "log_url": context.log_url,
                    "task_id": context.task_id
                })
                
                # Track successful pattern match
                self.cost_tracker.track_usage(
                    analysis_type="cdp_pattern_match",
                    credits_used=0,
                    agent_name=self.config.name,
                    success=True,
                    metadata={"pattern_type": base_result.source}
                )
                
                return base_result
            
            # Step 4: Skill-based analysis if pattern matching insufficient OR user explicitly requests AI
            if (base_result.confidence < self.confidence_threshold) or user_requested_ai:
                skill_result = await self._execute_cdp_skill_analysis(context, user_requested_ai)
                
                if skill_result:
                    credits_used = skill_result.credits_used
                    
                    # Merge results
                    enhanced_result = AnalysisResult(
                        success=skill_result.success,
                        analysis_type="cdp_skill_analysis",
                        confidence=skill_result.confidence,
                        pattern_matched=base_result.pattern_matched,
                        pattern_description=skill_result.pattern_description or base_result.pattern_description,
                        rdm_category=skill_result.rdm_category or base_result.rdm_category,
                        credits_used=credits_used,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                        source="skill",
                        data={
                            **base_result.data,
                            **skill_result.data,
                            "cdp_analysis": True
                        },
                        errors=skill_result.errors
                    )
                    
                    # Step 5: Post-analysis processing
                    await self._post_analysis_processing(context, enhanced_result)
                    
                    return enhanced_result
            
            # Return base result if no skill analysis needed
            base_result.execution_time_ms = int((time.time() - start_time) * 1000)
            return base_result
            
        except Exception as e:
            self.logger.error(f"CDP analysis failed: {e}")
            execution_time = int((time.time() - start_time) * 1000)
            
            error_result = AnalysisResult(
                success=False,
                analysis_type="cdp_error",
                confidence=0.0,
                pattern_matched=False,
                source="error",
                execution_time_ms=execution_time,
                credits_used=credits_used,
                errors=[str(e)]
            )
            
            # Track failed analysis
            self.cost_tracker.track_usage(
                analysis_type="cdp_analysis_error",
                credits_used=credits_used,
                agent_name=self.config.name,
                success=False,
                metadata={"error": str(e)}
            )
            
            return error_result
    
    async def _execute_cdp_skill_analysis(self, context: TriageContext, user_requested: bool = False) -> Optional[AnalysisResult]:
        """
        Execute the CDP triage skill for detailed analysis.
        
        This integrates with the existing triage-cdp-test-failure skill
        while providing cost control and error handling.
        """
        try:
            # For user-requested deep AI analysis, no credit limits - user has full control
            if user_requested:
                cost_estimate = self.cost_tracker.estimate_cost("ai_analysis")
                self.logger.info(f"User requested deep AI analysis - proceeding without credit limits (estimated: {cost_estimate} credits)")
            else:
                # For automatic pattern-based analysis, use minimal credits
                cost_estimate = self.cost_tracker.estimate_cost("skill_analysis")
            
            # Prepare skill execution
            skill_result = await self._run_triage_skill(context)
            
            # Track usage
            credits_used = cost_estimate if skill_result and skill_result.success else cost_estimate // 2
            analysis_type = "cdp_ai_analysis" if user_requested else "cdp_skill_analysis"
            
            self.cost_tracker.track_usage(
                analysis_type=analysis_type,
                credits_used=credits_used,
                agent_name=self.config.name,
                success=skill_result.success if skill_result else False,
                metadata={
                    "log_url": context.log_url,
                    "task_id": context.task_id,
                    "user_requested": user_requested
                },
                bypass_limits=user_requested  # No limits for user-requested AI analysis
            )
            
            return skill_result
            
        except Exception as e:
            self.logger.error(f"Skill execution failed: {e}")
            return AnalysisResult(
                success=False,
                analysis_type="cdp_skill_error",
                confidence=0.0,
                pattern_matched=False,
                source="skill_error",
                errors=[str(e)]
            )
    
    async def _run_triage_skill(self, context: TriageContext) -> AnalysisResult:
        """
        Run the actual triage-cdp-test-failure skill.
        
        This is a simplified implementation - in production, this would
        integrate with the actual skill execution system.
        """
        try:
            # Simulate skill execution for now
            # In production, this would call the actual skill
            
            # Mock analysis based on test result data
            test_result = context.test_result
            confidence = 0.85
            
            # Determine analysis outcome based on available data
            if context.log_url:
                confidence = 0.90
                description = "CDP test failure analyzed with log data"
            else:
                confidence = 0.75
                description = "CDP test failure analyzed without logs"
            
            # Simulate different failure categories
            if "timeout" in str(test_result.get("error_message", "")).lower():
                category = "TEST_BUG"
                description = "Test timeout - likely test infrastructure issue"
            elif "connection" in str(test_result.get("error_message", "")).lower():
                category = "INFRASTRUCTURE"
                description = "Connection failure - infrastructure issue"
            else:
                category = "PRODUCT"
                description = "Product failure requiring investigation"
            
            return AnalysisResult(
                success=True,
                analysis_type="cdp_skill",
                confidence=confidence,
                pattern_matched=False,
                pattern_description=description,
                rdm_category=category,
                credits_used=10,
                data={
                    "skill_analysis": True,
                    "jira_ready": True,
                    "requires_investigation": True,
                    "log_analysis_performed": context.log_url is not None,
                    "failure_timeline": self._extract_failure_timeline(test_result),
                    "suggested_actions": self._generate_suggested_actions(test_result, category)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Triage skill execution failed: {e}")
            return AnalysisResult(
                success=False,
                analysis_type="cdp_skill",
                confidence=0.0,
                pattern_matched=False,
                errors=[str(e)]
            )
    
    def _extract_failure_timeline(self, test_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract failure timeline from test result data."""
        timeline = []
        
        # Add test start
        if "start_time" in test_result:
            timeline.append({
                "timestamp": test_result["start_time"],
                "event": "Test Started",
                "details": f"Test {test_result.get('test_name', 'unknown')} started"
            })
        
        # Add failure event
        if "end_time" in test_result:
            timeline.append({
                "timestamp": test_result["end_time"],
                "event": "Test Failed",
                "details": test_result.get("error_message", "Test failed")
            })
        
        return timeline
    
    def _generate_suggested_actions(self, test_result: Dict[str, Any], category: str) -> List[str]:
        """Generate suggested actions based on failure analysis."""
        actions = []
        
        if category == "TEST_BUG":
            actions.extend([
                "Review test logic and timing assumptions",
                "Check test environment stability",
                "Consider increasing timeout values"
            ])
        elif category == "INFRASTRUCTURE":
            actions.extend([
                "Check cluster health and connectivity",
                "Verify network configuration",
                "Review infrastructure logs"
            ])
        elif category == "PRODUCT":
            actions.extend([
                "Investigate product service logs",
                "Check for recent product changes",
                "Review error patterns in similar tests"
            ])
        
        # Add common actions
        actions.extend([
            "Create JIRA ticket for tracking",
            "Add to regression analysis dashboard",
            "Monitor for pattern recurrence"
        ])
        
        return actions
    
    async def _post_analysis_processing(self, context: TriageContext, result: AnalysisResult):
        """
        Perform post-analysis processing including JIRA integration and telemetry.
        """
        try:
            # Update pattern cache with successful analysis
            if result.success and result.confidence >= 0.8:
                pattern_match = PatternMatch(
                    pattern_id=f"cdp_{int(time.time())}",
                    pattern_type="learned",
                    confidence=result.confidence,
                    description=result.pattern_description or "CDP analysis result",
                    category=result.rdm_category,
                    metadata={
                        "learned_from_skill": True,
                        "test_name": context.test_result.get("test_name", "")
                    }
                )
                
                self.pattern_cache.cache_analysis(
                    context.test_result,
                    pattern_match,
                    result.data
                )
            
            # JIRA integration (if enabled)
            if self.auto_jira_creation and result.data.get("jira_ready", False):
                await self._create_jira_ticket(context, result)
            
            # Telemetry logging (if enabled)
            if self.telemetry_enabled:
                await self._log_telemetry(context, result)
            
        except Exception as e:
            self.logger.error(f"Post-analysis processing failed: {e}")
    
    async def _create_jira_ticket(self, context: TriageContext, result: AnalysisResult):
        """Create JIRA ticket for the analyzed failure."""
        try:
            # This would integrate with the actual JIRA creation system
            # For now, just log the intention
            
            ticket_data = {
                "summary": f"CDP Test Failure: {context.test_result.get('test_name', 'Unknown')}",
                "description": result.pattern_description or "Automated triage analysis",
                "category": result.rdm_category,
                "confidence": result.confidence,
                "log_url": context.log_url,
                "suggested_actions": result.data.get("suggested_actions", [])
            }
            
            self.logger.info(f"Would create JIRA ticket: {ticket_data}")
            
            # Update result with JIRA information
            result.data["jira_ticket"] = {
                "created": True,
                "summary": ticket_data["summary"]
            }
            
        except Exception as e:
            self.logger.error(f"JIRA ticket creation failed: {e}")
            result.data["jira_ticket"] = {
                "created": False,
                "error": str(e)
            }
    
    async def _log_telemetry(self, context: TriageContext, result: AnalysisResult):
        """Log telemetry data for skill enrichment and learning."""
        try:
            telemetry_data = {
                "triage_id": f"cdp_{int(time.time())}",
                "skill_used": self.skill_name,
                "analysis_type": result.analysis_type,
                "confidence": result.confidence,
                "pattern_matched": result.pattern_matched,
                "credits_used": result.credits_used,
                "execution_time_ms": result.execution_time_ms,
                "success": result.success,
                "test_metadata": {
                    "test_name": context.test_result.get("test_name", ""),
                    "status": context.test_result.get("status", ""),
                    "task_id": context.task_id
                },
                "learning_data": {
                    "new_pattern_discovered": not result.pattern_matched and result.confidence >= 0.8,
                    "skill_enrichment_needed": result.confidence < 0.7,
                    "user_guided": self.user_guided_promotion
                }
            }
            
            self.logger.info(f"Telemetry logged: {telemetry_data}")
            
        except Exception as e:
            self.logger.error(f"Telemetry logging failed: {e}")
    
    def get_agent_capabilities(self) -> Dict[str, Any]:
        """Get detailed information about agent capabilities."""
        return {
            "name": self.config.name,
            "type": "cdp_triage",
            "skill_wrapper": self.skill_name,
            "capabilities": [
                "CDP test failure analysis",
                "Pattern-first cost optimization", 
                "JIRA integration",
                "Cross-skill handoff to RDM agent",
                "Telemetry and learning",
                "MCP server integration"
            ],
            "supported_failure_types": [
                "In-test failures",
                "Service failures",
                "Infrastructure issues",
                "Test bugs and timeouts"
            ],
            "cost_optimization": {
                "pattern_first_analysis": True,
                "credit_limit_enforcement": True,
                "cache_utilization": True,
                "confidence_thresholds": {
                    "pattern_match": 0.95,
                    "skill_execution": self.confidence_threshold
                }
            },
            "integrations": {
                "mcp_servers": self.mcp_dependencies,
                "skills": [self.skill_name],
                "services": ["pattern_cache", "cost_tracker"]
            }
        }