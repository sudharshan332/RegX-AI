"""
Cross-skill handoff system for RegX-AI agents.

Provides automated coordination and delegation between different agent types,
enabling seamless analysis workflows across multiple specialized agents.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple, Type
from dataclasses import dataclass, field
from enum import Enum

from .base import BaseAgent, AnalysisResult, AgentConfig
from .registry import AgentRegistry, agent_registry

logger = logging.getLogger(__name__)


class HandoffTrigger(Enum):
    """Types of handoff triggers."""
    FAILURE_CATEGORY = "failure_category"
    PATTERN_MATCH = "pattern_match"
    CONFIDENCE_THRESHOLD = "confidence_threshold"
    AGENT_CAPABILITY = "agent_capability"
    USER_DEFINED = "user_defined"


class HandoffStatus(Enum):
    """Status of handoff operations."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DELEGATED = "delegated"


@dataclass
class HandoffRule:
    """Configuration for agent handoff rules."""
    rule_id: str
    source_agent_type: str
    target_agent_type: str
    trigger: HandoffTrigger
    conditions: Dict[str, Any]
    priority: int = 1  # 1 (low) to 5 (high)
    context_preservation: bool = True
    bidirectional: bool = False
    
    def matches(self, test_result: Dict[str, Any], analysis_result: Optional[AnalysisResult] = None) -> bool:
        """Check if this handoff rule matches the current context."""
        if self.trigger == HandoffTrigger.FAILURE_CATEGORY:
            category = test_result.get("failure_analysis", {}).get("category", "")
            expected_category = self.conditions.get("category", "")
            return category == expected_category
        
        elif self.trigger == HandoffTrigger.PATTERN_MATCH:
            pattern_matched = test_result.get("pattern_matched", False)
            pattern_type = self.conditions.get("pattern_type", "")
            
            if not pattern_matched:
                return False
            
            if pattern_type:
                actual_pattern = test_result.get("pattern_description", "").lower()
                return pattern_type.lower() in actual_pattern
            
            return True
        
        elif self.trigger == HandoffTrigger.CONFIDENCE_THRESHOLD:
            if not analysis_result:
                return False
            
            threshold = self.conditions.get("threshold", 0.5)
            operator = self.conditions.get("operator", "less_than")  # less_than, greater_than
            
            if operator == "less_than":
                return analysis_result.confidence < threshold
            elif operator == "greater_than":
                return analysis_result.confidence > threshold
        
        elif self.trigger == HandoffTrigger.AGENT_CAPABILITY:
            required_capability = self.conditions.get("capability", "")
            test_type = self._infer_test_type(test_result)
            return required_capability.lower() in test_type.lower()
        
        return False
    
    def _infer_test_type(self, test_result: Dict[str, Any]) -> str:
        """Infer test type from test result data."""
        status = test_result.get("status", "").lower()
        test_name = test_result.get("test_name", "").lower()
        
        if status == "skipped" and "rdm" in str(test_result.get("failure_analysis", {})):
            return "rdm_deployment"
        elif "cdp" in test_name or "central" in test_name:
            return "cdp_test"
        elif "deployment" in test_name:
            return "deployment"
        
        return "generic"


@dataclass
class HandoffContext:
    """Context for agent handoff operations."""
    handoff_id: str
    source_agent: str
    target_agent: str
    test_result: Dict[str, Any]
    analysis_result: Optional[AnalysisResult] = None
    handoff_rule: Optional[HandoffRule] = None
    status: HandoffStatus = HandoffStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "status": self.status.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "metadata": self.metadata
        }


class CrossSkillHandoffManager:
    """
    Manager for coordinating handoffs between different agent types.
    
    Provides automated analysis workflow orchestration, enabling agents to
    delegate tasks to other specialized agents based on configurable rules.
    """
    
    def __init__(self, registry: Optional[AgentRegistry] = None):
        self.registry = registry or agent_registry
        self.handoff_rules: List[HandoffRule] = []
        self.active_handoffs: Dict[str, HandoffContext] = {}
        self.handoff_history: List[HandoffContext] = []
        
        # Load default handoff rules
        self._load_default_rules()
        
        logger.info(f"Cross-skill handoff manager initialized with {len(self.handoff_rules)} rules")
    
    def _load_default_rules(self):
        """Load default handoff rules for CDP and RDM agents."""
        default_rules = [
            # CDP to RDM handoff for deployment failures
            HandoffRule(
                rule_id="cdp_to_rdm_deployment",
                source_agent_type="cdp_triage",
                target_agent_type="rdm_analysis",
                trigger=HandoffTrigger.FAILURE_CATEGORY,
                conditions={"category": "DEVPROD_SERVICE:RDM"},
                priority=5,
                context_preservation=True
            ),
            
            # CDP to RDM handoff for skipped tests
            HandoffRule(
                rule_id="cdp_to_rdm_skipped",
                source_agent_type="analysis_agent",
                target_agent_type="deployment_agent", 
                trigger=HandoffTrigger.FAILURE_CATEGORY,
                conditions={"category": "DEVPROD_SERVICE:RDM"},
                priority=5,
                context_preservation=True
            ),
            
            # RDM to CDP handoff for test-specific issues
            HandoffRule(
                rule_id="rdm_to_cdp_test_issue",
                source_agent_type="rdm_analysis",
                target_agent_type="cdp_triage",
                trigger=HandoffTrigger.CONFIDENCE_THRESHOLD,
                conditions={"threshold": 0.6, "operator": "less_than"},
                priority=3,
                context_preservation=True,
                bidirectional=True
            ),
            
            # Pattern-based handoff for RDM patterns
            HandoffRule(
                rule_id="pattern_to_rdm",
                source_agent_type="analysis_agent",
                target_agent_type="deployment_agent",
                trigger=HandoffTrigger.PATTERN_MATCH,
                conditions={"pattern_type": "rdm"},
                priority=4,
                context_preservation=True
            )
        ]
        
        self.handoff_rules.extend(default_rules)
    
    def add_handoff_rule(self, rule: HandoffRule):
        """Add a new handoff rule."""
        self.handoff_rules.append(rule)
        # Sort by priority (highest first)
        self.handoff_rules.sort(key=lambda r: r.priority, reverse=True)
        logger.info(f"Added handoff rule: {rule.rule_id}")
    
    def remove_handoff_rule(self, rule_id: str) -> bool:
        """Remove a handoff rule by ID."""
        for i, rule in enumerate(self.handoff_rules):
            if rule.rule_id == rule_id:
                del self.handoff_rules[i]
                logger.info(f"Removed handoff rule: {rule_id}")
                return True
        return False
    
    async def evaluate_handoff(
        self, 
        source_agent: BaseAgent,
        test_result: Dict[str, Any],
        analysis_result: Optional[AnalysisResult] = None
    ) -> Optional[HandoffContext]:
        """
        Evaluate if a handoff is needed based on configured rules.
        
        Args:
            source_agent: Agent that performed initial analysis
            test_result: Original test result data
            analysis_result: Result of analysis (optional)
            
        Returns:
            HandoffContext if handoff is needed, None otherwise
        """
        try:
            source_agent_type = source_agent.config.type
            
            # Find matching handoff rules
            matching_rules = []
            for rule in self.handoff_rules:
                if rule.source_agent_type == source_agent_type:
                    if rule.matches(test_result, analysis_result):
                        matching_rules.append(rule)
            
            if not matching_rules:
                return None
            
            # Use highest priority rule
            best_rule = matching_rules[0]
            
            # Check if target agent type is available
            target_agents = self.registry.get_healthy_agents_by_type(best_rule.target_agent_type)
            if not target_agents:
                logger.warning(f"No healthy agents available for handoff to {best_rule.target_agent_type}")
                return None
            
            # Create handoff context
            handoff_id = f"handoff_{int(time.time())}_{len(self.active_handoffs)}"
            
            context = HandoffContext(
                handoff_id=handoff_id,
                source_agent=source_agent.config.name,
                target_agent=target_agents[0].config.name,
                test_result=test_result,
                analysis_result=analysis_result,
                handoff_rule=best_rule,
                status=HandoffStatus.PENDING,
                metadata={
                    "rule_id": best_rule.rule_id,
                    "trigger": best_rule.trigger.value,
                    "source_agent_type": source_agent_type,
                    "target_agent_type": best_rule.target_agent_type
                }
            )
            
            logger.info(f"Handoff needed: {source_agent.config.name} -> {target_agents[0].config.name} (rule: {best_rule.rule_id})")
            return context
            
        except Exception as e:
            logger.error(f"Handoff evaluation failed: {e}")
            return None
    
    async def execute_handoff(self, context: HandoffContext) -> AnalysisResult:
        """
        Execute the handoff to the target agent.
        
        Args:
            context: Handoff context with source and target information
            
        Returns:
            Analysis result from target agent
        """
        try:
            # Add to active handoffs
            self.active_handoffs[context.handoff_id] = context
            context.status = HandoffStatus.IN_PROGRESS
            
            # Get target agent
            target_agent = self.registry.get_agent(context.target_agent)
            if not target_agent:
                raise ValueError(f"Target agent not found: {context.target_agent}")
            
            # Prepare enhanced test result with handoff context
            enhanced_test_result = context.test_result.copy()
            if context.handoff_rule and context.handoff_rule.context_preservation:
                enhanced_test_result["_handoff_context"] = {
                    "handoff_id": context.handoff_id,
                    "source_agent": context.source_agent,
                    "source_analysis": context.analysis_result.to_dict() if context.analysis_result else None,
                    "handoff_rule": context.handoff_rule.rule_id,
                    "handoff_reason": context.handoff_rule.trigger.value
                }
            
            # Preserve user AI request through handoff
            user_requested_ai = enhanced_test_result.get("_analysis_context", {}).get("user_requested_ai", False)
            
            # Execute analysis on target agent
            logger.info(f"Executing handoff {context.handoff_id}: {context.source_agent} -> {context.target_agent}")
            
            result = await target_agent.analyze(enhanced_test_result, user_requested_ai)
            
            # Update handoff context
            context.status = HandoffStatus.COMPLETED
            context.completed_at = time.time()
            
            # Enhance result with handoff information
            if result.success:
                result.data["handoff_execution"] = {
                    "handoff_id": context.handoff_id,
                    "source_agent": context.source_agent,
                    "handoff_rule": context.handoff_rule.rule_id if context.handoff_rule else None,
                    "execution_time_ms": int((context.completed_at - context.created_at) * 1000)
                }
            
            # Move to history
            self._complete_handoff(context)
            
            logger.info(f"Handoff {context.handoff_id} completed successfully")
            return result
            
        except Exception as e:
            logger.error(f"Handoff execution failed: {e}")
            
            # Update context with error
            context.status = HandoffStatus.FAILED
            context.error = str(e)
            context.completed_at = time.time()
            
            # Move to history
            self._complete_handoff(context)
            
            # Return error result
            return AnalysisResult(
                success=False,
                analysis_type="handoff_error",
                confidence=0.0,
                pattern_matched=False,
                source="handoff_error",
                errors=[str(e)],
                data={
                    "handoff_id": context.handoff_id,
                    "handoff_error": True
                }
            )
    
    def _complete_handoff(self, context: HandoffContext):
        """Move handoff from active to history."""
        if context.handoff_id in self.active_handoffs:
            del self.active_handoffs[context.handoff_id]
        
        self.handoff_history.append(context)
        
        # Keep only last 1000 handoffs in history
        if len(self.handoff_history) > 1000:
            self.handoff_history = self.handoff_history[-1000:]
    
    async def orchestrate_analysis(
        self,
        test_result: Dict[str, Any],
        preferred_agent_type: Optional[str] = None,
        user_requested_ai: bool = False
    ) -> AnalysisResult:
        """
        Orchestrate analysis with automatic handoff capabilities.
        
        Args:
            test_result: Test result data to analyze
            preferred_agent_type: Preferred agent type (optional)
            
        Returns:
            Final analysis result (possibly from multiple agents)
        """
        try:
            # Step 1: Get initial analysis
            initial_result = await self.registry.analyze_with_best_agent(
                test_result, 
                preferred_agent_type,
                user_requested_ai
            )
            
            if not initial_result:
                return AnalysisResult(
                    success=False,
                    analysis_type="orchestration_error",
                    confidence=0.0,
                    pattern_matched=False,
                    source="no_agent_available",
                    errors=["No capable agent found"]
                )
            
            # Step 2: Check if handoff is needed
            source_agent_name = initial_result.data.get("agent_name")
            source_agent = self.registry.get_agent(source_agent_name) if source_agent_name else None
            
            if not source_agent:
                # Try to find agent by result characteristics
                if initial_result.data.get("requires_handoff"):
                    handoff_target = initial_result.data.get("handoff_target")
                    if handoff_target:
                        target_agents = self.registry.get_healthy_agents_by_type(handoff_target)
                        if target_agents:
                            enhanced_test_result = test_result.copy()
                            enhanced_test_result["_direct_handoff"] = True
                            return await target_agents[0].analyze(enhanced_test_result, user_requested_ai)
                
                return initial_result
            
            # Evaluate handoff
            handoff_context = await self.evaluate_handoff(
                source_agent,
                test_result,
                initial_result
            )
            
            # Step 3: Execute handoff if needed
            if handoff_context:
                handoff_result = await self.execute_handoff(handoff_context)
                
                # Merge results if both are successful
                if handoff_result.success and initial_result.success:
                    merged_result = self._merge_analysis_results(initial_result, handoff_result)
                    merged_result.data["orchestration"] = {
                        "multi_agent_analysis": True,
                        "handoff_executed": True,
                        "handoff_id": handoff_context.handoff_id
                    }
                    return merged_result
                elif handoff_result.success:
                    return handoff_result
                else:
                    # Handoff failed, return initial result with warning
                    initial_result.data["handoff_warning"] = {
                        "handoff_attempted": True,
                        "handoff_failed": True,
                        "error": handoff_result.errors[0] if handoff_result.errors else "Unknown"
                    }
                    return initial_result
            
            # No handoff needed
            return initial_result
            
        except Exception as e:
            logger.error(f"Analysis orchestration failed: {e}")
            return AnalysisResult(
                success=False,
                analysis_type="orchestration_error",
                confidence=0.0,
                pattern_matched=False,
                source="orchestration_error",
                errors=[str(e)]
            )
    
    def _merge_analysis_results(
        self, 
        primary_result: AnalysisResult, 
        secondary_result: AnalysisResult
    ) -> AnalysisResult:
        """Merge two analysis results into a comprehensive result."""
        # Use the higher confidence result as primary
        if secondary_result.confidence > primary_result.confidence:
            primary_result, secondary_result = secondary_result, primary_result
        
        # Merge data
        merged_data = primary_result.data.copy()
        merged_data["secondary_analysis"] = {
            "analysis_type": secondary_result.analysis_type,
            "confidence": secondary_result.confidence,
            "pattern_matched": secondary_result.pattern_matched,
            "source": secondary_result.source,
            "data": secondary_result.data
        }
        
        # Create merged result
        return AnalysisResult(
            success=True,
            analysis_type="merged_analysis",
            confidence=max(primary_result.confidence, secondary_result.confidence * 0.8),
            pattern_matched=primary_result.pattern_matched or secondary_result.pattern_matched,
            pattern_description=primary_result.pattern_description or secondary_result.pattern_description,
            rdm_category=primary_result.rdm_category or secondary_result.rdm_category,
            credits_used=primary_result.credits_used + secondary_result.credits_used,
            execution_time_ms=primary_result.execution_time_ms + secondary_result.execution_time_ms,
            source="merged",
            data=merged_data,
            errors=primary_result.errors + secondary_result.errors
        )
    
    def get_handoff_statistics(self, days: int = 7) -> Dict[str, Any]:
        """Get handoff statistics for the specified period."""
        current_time = time.time()
        cutoff_time = current_time - (days * 24 * 3600)
        
        # Filter recent handoffs
        recent_handoffs = [
            h for h in self.handoff_history 
            if h.created_at >= cutoff_time
        ]
        
        # Calculate statistics
        total_handoffs = len(recent_handoffs)
        successful_handoffs = len([h for h in recent_handoffs if h.status == HandoffStatus.COMPLETED])
        failed_handoffs = len([h for h in recent_handoffs if h.status == HandoffStatus.FAILED])
        
        # Rule usage
        rule_usage = {}
        for handoff in recent_handoffs:
            if handoff.handoff_rule:
                rule_id = handoff.handoff_rule.rule_id
                rule_usage[rule_id] = rule_usage.get(rule_id, 0) + 1
        
        # Agent combinations
        agent_combinations = {}
        for handoff in recent_handoffs:
            combo = f"{handoff.source_agent} -> {handoff.target_agent}"
            agent_combinations[combo] = agent_combinations.get(combo, 0) + 1
        
        return {
            "period_days": days,
            "total_handoffs": total_handoffs,
            "successful_handoffs": successful_handoffs,
            "failed_handoffs": failed_handoffs,
            "success_rate": successful_handoffs / max(1, total_handoffs),
            "active_handoffs": len(self.active_handoffs),
            "rule_usage": rule_usage,
            "agent_combinations": agent_combinations,
            "average_execution_time_ms": (
                sum(
                    (h.completed_at - h.created_at) * 1000
                    for h in recent_handoffs
                    if h.completed_at
                ) / max(1, len([h for h in recent_handoffs if h.completed_at]))
            )
        }
    
    def get_active_handoffs(self) -> List[Dict[str, Any]]:
        """Get list of currently active handoffs."""
        return [context.to_dict() for context in self.active_handoffs.values()]
    
    def get_handoff_rules(self) -> List[Dict[str, Any]]:
        """Get list of configured handoff rules."""
        return [
            {
                "rule_id": rule.rule_id,
                "source_agent_type": rule.source_agent_type,
                "target_agent_type": rule.target_agent_type,
                "trigger": rule.trigger.value,
                "conditions": rule.conditions,
                "priority": rule.priority,
                "context_preservation": rule.context_preservation,
                "bidirectional": rule.bidirectional
            }
            for rule in self.handoff_rules
        ]


# Global handoff manager instance
handoff_manager = CrossSkillHandoffManager()