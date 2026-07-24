"""
Base agent classes for the RegX-AI agent framework.

Provides foundational classes for cost-effective analysis agents with pattern matching,
skill integration, and credit tracking capabilities.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
import yaml
import os

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for an agent instance."""
    name: str
    type: str
    skill_wrapper: Optional[str] = None
    cost_optimization: Dict[str, Any] = field(default_factory=dict)
    triggers: List[Dict[str, Any]] = field(default_factory=list)
    pattern_matching: Dict[str, Any] = field(default_factory=dict)
    mcp_dependencies: List[str] = field(default_factory=list)
    cross_skill_handoff: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, config_path: str) -> "AgentConfig":
        """Load agent configuration from YAML file."""
        try:
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)
            return cls(**config_data)
        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            raise


@dataclass
class AnalysisResult:
    """Result of an agent analysis operation."""
    success: bool
    analysis_type: str
    confidence: float
    pattern_matched: bool
    pattern_description: Optional[str] = None
    rdm_category: Optional[str] = None
    credits_used: int = 0
    execution_time_ms: int = 0
    source: str = "agent"  # cache, pattern, skill, ai
    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@dataclass
class AgentMetrics:
    """Metrics for agent performance and cost tracking."""
    total_analyses: int = 0
    successful_analyses: int = 0
    pattern_matches: int = 0
    cache_hits: int = 0
    credits_used: int = 0
    average_execution_time_ms: float = 0
    last_execution: Optional[float] = None
    
    def update(self, result: AnalysisResult):
        """Update metrics with a new analysis result."""
        self.total_analyses += 1
        if result.success:
            self.successful_analyses += 1
        if result.pattern_matched:
            self.pattern_matches += 1
        if result.source == "cache":
            self.cache_hits += 1
        
        self.credits_used += result.credits_used
        
        # Update average execution time
        if self.average_execution_time_ms == 0:
            self.average_execution_time_ms = result.execution_time_ms
        else:
            self.average_execution_time_ms = (
                (self.average_execution_time_ms * (self.total_analyses - 1) + 
                 result.execution_time_ms) / self.total_analyses
            )
        
        self.last_execution = time.time()


class BaseAgent(ABC):
    """
    Base class for all RegX-AI agents.
    
    Provides common functionality for cost tracking, pattern matching,
    and configuration management.
    """
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.metrics = AgentMetrics()
        self.is_active = False
        self.logger = logging.getLogger(f"agent.{config.name}")
        
        # Initialize services
        self._pattern_cache = None
        self._cost_tracker = None
        self._mcp_bridge = None
        
        self.logger.info(f"Initialized agent: {config.name} (type: {config.type})")
    
    @abstractmethod
    async def analyze(self, test_result: Dict[str, Any], user_requested_ai: bool = False) -> AnalysisResult:
        """
        Perform analysis on a test result.
        
        Args:
            test_result: Dictionary containing test failure data
            
        Returns:
            AnalysisResult with analysis findings and metadata
        """
        pass
    
    def can_handle(self, test_result: Dict[str, Any]) -> bool:
        """
        Check if this agent can handle the given test result.
        
        Args:
            test_result: Dictionary containing test failure data
            
        Returns:
            True if agent can handle this test result
        """
        # Check triggers from configuration
        for trigger in self.config.triggers:
            if self._matches_trigger(test_result, trigger):
                return True
        return False
    
    def _matches_trigger(self, test_result: Dict[str, Any], trigger: Dict[str, Any]) -> bool:
        """Check if test result matches a trigger condition."""
        event = trigger.get("event")
        conditions = trigger.get("conditions", [])
        
        # Check event type
        if event == "test_failed" and test_result.get("status", "").lower() not in ("failed", "failure"):
            return False
        elif event == "test_skipped" and test_result.get("status", "").lower() != "skipped":
            return False
        elif event == "deployment_failed" and not test_result.get("deployment_failure"):
            return False
        
        # Check conditions
        for condition in conditions:
            if not self._evaluate_condition(test_result, condition):
                return False
        
        return True
    
    def _evaluate_condition(self, test_result: Dict[str, Any], condition: str) -> bool:
        """Evaluate a condition string against test result data."""
        try:
            # Simple condition evaluation - can be enhanced
            if "!=" in condition:
                field, value = condition.split("!=", 1)
                field = field.strip()
                value = value.strip().strip('"')
                return test_result.get(field.replace(".", "_")) != value
            elif "==" in condition:
                field, value = condition.split("==", 1)
                field = field.strip()
                value = value.strip().strip('"')
                return test_result.get(field.replace(".", "_")) == value
            elif condition.startswith("pattern_matched"):
                if "!=" in condition:
                    return not test_result.get("pattern_matched", False)
                else:
                    return test_result.get("pattern_matched", False)
            
            return True
        except Exception as e:
            self.logger.warning(f"Failed to evaluate condition '{condition}': {e}")
            return False
    
    def start(self):
        """Start the agent."""
        self.is_active = True
        self.logger.info(f"Agent {self.config.name} started")
    
    def stop(self):
        """Stop the agent."""
        self.is_active = False
        self.logger.info(f"Agent {self.config.name} stopped")
    
    def get_metrics(self) -> AgentMetrics:
        """Get current agent metrics."""
        return self.metrics
    
    def get_status(self) -> Dict[str, Any]:
        """Get agent status information."""
        return {
            "name": self.config.name,
            "type": self.config.type,
            "active": self.is_active,
            "metrics": {
                "total_analyses": self.metrics.total_analyses,
                "success_rate": (
                    self.metrics.successful_analyses / self.metrics.total_analyses
                    if self.metrics.total_analyses > 0 else 0
                ),
                "pattern_match_rate": (
                    self.metrics.pattern_matches / self.metrics.total_analyses
                    if self.metrics.total_analyses > 0 else 0
                ),
                "cache_hit_rate": (
                    self.metrics.cache_hits / self.metrics.total_analyses
                    if self.metrics.total_analyses > 0 else 0
                ),
                "credits_used": self.metrics.credits_used,
                "avg_execution_time_ms": self.metrics.average_execution_time_ms,
                "last_execution": self.metrics.last_execution
            }
        }


class SkillWrapperAgent(BaseAgent):
    """
    Agent that wraps existing RegX-AI skills for seamless integration.
    
    Provides cost optimization and pattern matching on top of existing
    skill implementations without modifying the original skills.
    """
    
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        
        if not config.skill_wrapper:
            raise ValueError("SkillWrapperAgent requires skill_wrapper in config")
        
        self.skill_name = config.skill_wrapper
        self.skill_path = self._resolve_skill_path()
        
        # Cost optimization settings
        cost_config = config.cost_optimization
        self.pattern_first = cost_config.get("pattern_first", True)
        self.credit_limit_daily = cost_config.get("credit_limit_daily", 100)
        self.confidence_threshold = cost_config.get("confidence_threshold", 0.7)
        
        self.logger.info(f"Initialized skill wrapper for: {self.skill_name}")
    
    def _resolve_skill_path(self) -> str:
        """Resolve the path to the skill directory."""
        # Assuming skills are in .cursor/skills/ directory
        workspace_root = "/Users/sudharshan.musali/regx/RegX-AI"
        skill_path = os.path.join(workspace_root, ".cursor", "skills", self.skill_name)
        
        if not os.path.exists(skill_path):
            raise FileNotFoundError(f"Skill not found: {skill_path}")
        
        return skill_path
    
    async def analyze(self, test_result: Dict[str, Any], user_requested_ai: bool = False) -> AnalysisResult:
        """
        Perform cost-optimized analysis using pattern matching and skill integration.
        
        Implementation follows the cost-optimized pipeline:
        1. Check pattern cache
        2. Simple pattern matching
        3. RDM pattern database
        4. Regex pattern matching
        5. Skill-based analysis (if needed and credits available)
        """
        start_time = time.time()
        credits_used = 0
        
        try:
            # Step 1: Check pattern cache
            if self._pattern_cache:
                cached_result = await self._check_pattern_cache(test_result)
                if cached_result and cached_result.confidence >= 0.9:
                    cached_result.source = "cache"
                    execution_time = int((time.time() - start_time) * 1000)
                    cached_result.execution_time_ms = execution_time
                    self.metrics.update(cached_result)
                    return cached_result
            
            # Step 2: Simple pattern matching
            simple_match = self._check_simple_patterns(test_result)
            if simple_match and simple_match.confidence >= self.confidence_threshold:
                simple_match.source = "pattern"
                execution_time = int((time.time() - start_time) * 1000)
                simple_match.execution_time_ms = execution_time
                self.metrics.update(simple_match)
                return simple_match
            
            # Step 3: RDM pattern database
            rdm_match = self._check_rdm_patterns(test_result)
            if rdm_match and rdm_match.confidence >= 0.95:
                rdm_match.source = "pattern"
                execution_time = int((time.time() - start_time) * 1000)
                rdm_match.execution_time_ms = execution_time
                self.metrics.update(rdm_match)
                return rdm_match
            
            # Step 4: Check credit availability
            if self._cost_tracker and not self._cost_tracker.can_use_credits(
                user_id="system",
                team_id="regx",
                cost_estimate=10
            ):
                # Return best pattern match with confidence score
                best_match = rdm_match or simple_match
                if best_match:
                    best_match.source = "pattern_fallback"
                    best_match.data["credit_limit_reached"] = True
                    execution_time = int((time.time() - start_time) * 1000)
                    best_match.execution_time_ms = execution_time
                    self.metrics.update(best_match)
                    return best_match
                
                # No pattern match and no credits
                return AnalysisResult(
                    success=False,
                    analysis_type="skill_wrapper",
                    confidence=0.0,
                    pattern_matched=False,
                    source="no_credits",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    errors=["Credit limit reached, no pattern match available"]
                )
            
            # Step 5: Skill-based analysis
            skill_result = await self._execute_skill_analysis(test_result)
            credits_used = 10  # Estimate for skill execution
            
            if self._cost_tracker:
                self._cost_tracker.track_usage("skill_analysis", credits_used)
            
            skill_result.credits_used = credits_used
            skill_result.source = "skill"
            execution_time = int((time.time() - start_time) * 1000)
            skill_result.execution_time_ms = execution_time
            
            # Update pattern cache with results
            if self._pattern_cache and skill_result.success:
                await self._update_pattern_cache(test_result, skill_result)
            
            self.metrics.update(skill_result)
            return skill_result
            
        except Exception as e:
            self.logger.error(f"Analysis failed: {e}")
            execution_time = int((time.time() - start_time) * 1000)
            error_result = AnalysisResult(
                success=False,
                analysis_type="skill_wrapper",
                confidence=0.0,
                pattern_matched=False,
                source="error",
                execution_time_ms=execution_time,
                credits_used=credits_used,
                errors=[str(e)]
            )
            self.metrics.update(error_result)
            return error_result
    
    def _check_simple_patterns(self, test_result: Dict[str, Any]) -> Optional[AnalysisResult]:
        """Check simple pattern matching based on status and category."""
        status = test_result.get("status", "").lower()
        failure_category = test_result.get("failure_analysis", {}).get("category", "")
        
        # RDM deployment failure pattern
        if (status == "skipped" and 
            failure_category == "DEVPROD_SERVICE:RDM"):
            return AnalysisResult(
                success=True,
                analysis_type="simple_pattern",
                confidence=0.95,
                pattern_matched=True,
                pattern_description="RDM deployment failure - test skipped",
                rdm_category="INFRASTRUCTURE",
                data={"simple_pattern": "rdm_deployment_failure"}
            )
        
        # Test failure patterns
        if status in ("failed", "failure"):
            return AnalysisResult(
                success=True,
                analysis_type="simple_pattern",
                confidence=0.6,
                pattern_matched=True,
                pattern_description="Test failure detected - requires analysis",
                data={"simple_pattern": "test_failure"}
            )
        
        return None
    
    def _check_rdm_patterns(self, test_result: Dict[str, Any]) -> Optional[AnalysisResult]:
        """Check against RDM pattern database."""
        # This would integrate with the existing pattern database
        # For now, return a basic implementation
        
        if test_result.get("pattern_matched"):
            return AnalysisResult(
                success=True,
                analysis_type="rdm_pattern",
                confidence=0.95,
                pattern_matched=True,
                pattern_description=test_result.get("pattern_description", "RDM pattern matched"),
                rdm_category=test_result.get("rdm_category", "PRODUCT"),
                data={"rdm_pattern": test_result.get("pattern_description")}
            )
        
        return None
    
    async def _check_pattern_cache(self, test_result: Dict[str, Any]) -> Optional[AnalysisResult]:
        """Check pattern cache for existing analysis."""
        # This would integrate with the pattern cache service
        return None
    
    async def _update_pattern_cache(self, test_result: Dict[str, Any], result: AnalysisResult):
        """Update pattern cache with new analysis result."""
        # This would integrate with the pattern cache service
        pass
    
    async def _execute_skill_analysis(self, test_result: Dict[str, Any]) -> AnalysisResult:
        """Execute the wrapped skill for detailed analysis."""
        # This would integrate with the existing skill system
        # For now, return a mock result
        
        return AnalysisResult(
            success=True,
            analysis_type="skill_analysis",
            confidence=0.85,
            pattern_matched=False,
            pattern_description=f"Analyzed using {self.skill_name}",
            data={"skill_used": self.skill_name}
        )