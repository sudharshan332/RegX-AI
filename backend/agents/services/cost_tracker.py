"""
Cost tracking and credit management system for RegX-AI agents.

Provides budget enforcement, usage analytics, and cost optimization to prevent
excessive AI credit consumption while maintaining analysis quality.
"""

import json
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import os

logger = logging.getLogger(__name__)


@dataclass
class CreditUsage:
    """Record of credit usage for analytics."""
    timestamp: float
    user_id: str
    team_id: str
    analysis_type: str
    credits_used: int
    agent_name: str
    success: bool
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "team_id": self.team_id,
            "analysis_type": self.analysis_type,
            "credits_used": self.credits_used,
            "agent_name": self.agent_name,
            "success": self.success,
            "metadata": self.metadata
        }


@dataclass
class CreditBudget:
    """Credit budget configuration for users/teams."""
    entity_id: str  # user_id or team_id
    entity_type: str  # "user" or "team"
    daily_limit: int
    weekly_limit: int
    monthly_limit: int
    priority: int = 1  # 1 (low) to 5 (high)
    allow_overrun: bool = False
    overrun_limit: int = 0  # Additional credits after limit
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "daily_limit": self.daily_limit,
            "weekly_limit": self.weekly_limit,
            "monthly_limit": self.monthly_limit,
            "priority": self.priority,
            "allow_overrun": self.allow_overrun,
            "overrun_limit": self.overrun_limit
        }


@dataclass
class UsageSummary:
    """Summary of credit usage for a time period."""
    period_start: float
    period_end: float
    total_credits: int
    successful_analyses: int
    failed_analyses: int
    analysis_breakdown: Dict[str, int]  # analysis_type -> credit_count
    agent_breakdown: Dict[str, int]    # agent_name -> credit_count
    hourly_usage: List[int]            # Credits used per hour
    
    @property
    def success_rate(self) -> float:
        total = self.successful_analyses + self.failed_analyses
        return self.successful_analyses / max(1, total)
    
    @property
    def cost_per_success(self) -> float:
        return self.total_credits / max(1, self.successful_analyses)


class CostTracker:
    """
    Credit monitoring and budget enforcement system.
    
    Tracks AI credit usage, enforces budget limits, and provides analytics
    to optimize cost-effectiveness of analysis operations.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.data_dir = self.config.get(
            "data_dir", 
            "/Users/sudharshan.musali/regx/RegX-AI/backend/agents/data"
        )
        
        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Credit budgets
        self.budgets: Dict[str, CreditBudget] = {}
        
        # Usage tracking
        self.usage_history: List[CreditUsage] = []
        self.daily_usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))  # date -> entity -> credits
        self.weekly_usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))  # week -> entity -> credits
        self.monthly_usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))  # month -> entity -> credits
        
        # Cost estimation
        self.analysis_cost_estimates = {
            "simple_pattern": 0,
            "rdm_pattern": 0,
            "regex_pattern": 1,
            "skill_analysis": 5,  # Reduced cost for skill wrapper without AI
            "ai_analysis": 25,    # User-requested deep AI analysis
            "comprehensive_analysis": 50,  # Full AI analysis with multiple tools
            "pattern_learning": 15,  # When AI results are used to improve patterns
            
            # Intelligent Triage Analysis Types
            "pattern_match": 0,              # Pattern matching (free)
            "first_level_ai_analysis": 15,  # JITA + Glean analysis  
            "rdm_pattern_with_glean": 5,     # Pattern + Glean search
            "intermittent_analysis": 15,     # History-based intermittent analysis
            "existing_issue_detection": 5,   # Glean search for known issues
        }
        
        # Load existing data
        self._load_budgets()
        self._load_usage_history()
        
        # Initialize default budgets
        self._initialize_default_budgets()
        
        logger.info(f"Cost tracker initialized with {len(self.budgets)} budgets")
    
    def _load_budgets(self):
        """Load credit budgets from file."""
        budgets_file = os.path.join(self.data_dir, "credit_budgets.json")
        try:
            if os.path.exists(budgets_file):
                with open(budgets_file, 'r') as f:
                    budgets_data = json.load(f)
                
                for budget_data in budgets_data:
                    budget = CreditBudget(**budget_data)
                    self.budgets[budget.entity_id] = budget
                    
        except Exception as e:
            logger.error(f"Failed to load credit budgets: {e}")
    
    def _save_budgets(self):
        """Save credit budgets to file."""
        budgets_file = os.path.join(self.data_dir, "credit_budgets.json")
        try:
            budgets_data = [budget.to_dict() for budget in self.budgets.values()]
            with open(budgets_file, 'w') as f:
                json.dump(budgets_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save credit budgets: {e}")
    
    def _load_usage_history(self):
        """Load usage history from file."""
        usage_file = os.path.join(self.data_dir, "credit_usage.jsonl")
        try:
            if os.path.exists(usage_file):
                with open(usage_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            usage_data = json.loads(line)
                            usage = CreditUsage(**usage_data)
                            self.usage_history.append(usage)
                
                # Rebuild usage summaries
                self._rebuild_usage_summaries()
                
        except Exception as e:
            logger.error(f"Failed to load usage history: {e}")
    
    def _save_usage_record(self, usage: CreditUsage):
        """Append usage record to file."""
        usage_file = os.path.join(self.data_dir, "credit_usage.jsonl")
        try:
            with open(usage_file, 'a') as f:
                f.write(json.dumps(usage.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to save usage record: {e}")
    
    def _initialize_default_budgets(self):
        """Initialize default credit budgets for common teams."""
        default_budgets = [
            {
                "entity_id": "regx_team",
                "entity_type": "team",
                "daily_limit": 500,
                "weekly_limit": 2000,
                "monthly_limit": 8000,
                "priority": 3,
                "allow_overrun": True,
                "overrun_limit": 100
            },
            {
                "entity_id": "cdp_team", 
                "entity_type": "team",
                "daily_limit": 300,
                "weekly_limit": 1500,
                "monthly_limit": 6000,
                "priority": 3,
                "allow_overrun": True,
                "overrun_limit": 50
            },
            {
                "entity_id": "system",
                "entity_type": "user",
                "daily_limit": 200,
                "weekly_limit": 1000,
                "monthly_limit": 4000,
                "priority": 2,
                "allow_overrun": False,
                "overrun_limit": 0
            }
        ]
        
        for budget_data in default_budgets:
            entity_id = budget_data["entity_id"]
            if entity_id not in self.budgets:
                self.budgets[entity_id] = CreditBudget(**budget_data)
        
        self._save_budgets()
    
    def _rebuild_usage_summaries(self):
        """Rebuild usage summaries from history."""
        for usage in self.usage_history:
            date_key = datetime.fromtimestamp(usage.timestamp).strftime("%Y-%m-%d")
            week_key = datetime.fromtimestamp(usage.timestamp).strftime("%Y-W%U")
            month_key = datetime.fromtimestamp(usage.timestamp).strftime("%Y-%m")
            
            # Daily usage
            self.daily_usage[date_key][usage.user_id] += usage.credits_used
            self.daily_usage[date_key][usage.team_id] += usage.credits_used
            
            # Weekly usage
            self.weekly_usage[week_key][usage.user_id] += usage.credits_used
            self.weekly_usage[week_key][usage.team_id] += usage.credits_used
            
            # Monthly usage
            self.monthly_usage[month_key][usage.user_id] += usage.credits_used
            self.monthly_usage[month_key][usage.team_id] += usage.credits_used
    
    def estimate_cost(self, analysis_type: str) -> int:
        """Estimate credit cost for analysis type."""
        return self.analysis_cost_estimates.get(analysis_type, 10)
    
    def can_use_credits(
        self, 
        user_id: str, 
        team_id: str, 
        cost_estimate: int
    ) -> Tuple[bool, str]:
        """
        Check if credits can be used within budget limits.
        
        Args:
            user_id: User identifier
            team_id: Team identifier  
            cost_estimate: Estimated credit cost
            
        Returns:
            Tuple of (can_use, reason)
        """
        current_time = time.time()
        today = datetime.fromtimestamp(current_time).strftime("%Y-%m-%d")
        this_week = datetime.fromtimestamp(current_time).strftime("%Y-W%U")
        this_month = datetime.fromtimestamp(current_time).strftime("%Y-%m")
        
        # Check user budget
        user_budget = self.budgets.get(user_id)
        if user_budget:
            user_daily = self.daily_usage[today].get(user_id, 0)
            user_weekly = self.weekly_usage[this_week].get(user_id, 0)
            user_monthly = self.monthly_usage[this_month].get(user_id, 0)
            
            # Check daily limit
            if user_daily + cost_estimate > user_budget.daily_limit:
                if not user_budget.allow_overrun or user_daily + cost_estimate > user_budget.daily_limit + user_budget.overrun_limit:
                    return False, f"User daily limit exceeded ({user_daily}/{user_budget.daily_limit})"
            
            # Check weekly limit
            if user_weekly + cost_estimate > user_budget.weekly_limit:
                return False, f"User weekly limit exceeded ({user_weekly}/{user_budget.weekly_limit})"
            
            # Check monthly limit
            if user_monthly + cost_estimate > user_budget.monthly_limit:
                return False, f"User monthly limit exceeded ({user_monthly}/{user_budget.monthly_limit})"
        
        # Check team budget
        team_budget = self.budgets.get(team_id)
        if team_budget:
            team_daily = self.daily_usage[today].get(team_id, 0)
            team_weekly = self.weekly_usage[this_week].get(team_id, 0)
            team_monthly = self.monthly_usage[this_month].get(team_id, 0)
            
            # Check daily limit
            if team_daily + cost_estimate > team_budget.daily_limit:
                if not team_budget.allow_overrun or team_daily + cost_estimate > team_budget.daily_limit + team_budget.overrun_limit:
                    return False, f"Team daily limit exceeded ({team_daily}/{team_budget.daily_limit})"
            
            # Check weekly limit
            if team_weekly + cost_estimate > team_budget.weekly_limit:
                return False, f"Team weekly limit exceeded ({team_weekly}/{team_budget.weekly_limit})"
            
            # Check monthly limit
            if team_monthly + cost_estimate > team_budget.monthly_limit:
                return False, f"Team monthly limit exceeded ({team_monthly}/{team_budget.monthly_limit})"
        
        return True, "Credits available"
    
    def track_usage(
        self,
        analysis_type: str,
        credits_used: int,
        user_id: str = "system",
        team_id: str = "regx_team",
        agent_name: str = "unknown",
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        bypass_limits: bool = False
    ):
        """
        Track credit usage for analytics and budget enforcement.
        
        Args:
            analysis_type: Type of analysis performed
            credits_used: Number of credits consumed
            user_id: User who initiated the analysis
            team_id: Team responsible for the analysis
            agent_name: Agent that performed the analysis
            success: Whether the analysis was successful
            metadata: Additional metadata for the usage record
        """
        current_time = time.time()
        
        # Add bypass flag to metadata for tracking
        enhanced_metadata = metadata or {}
        if bypass_limits:
            enhanced_metadata["bypass_limits"] = True
            enhanced_metadata["user_requested"] = True
        
        usage = CreditUsage(
            timestamp=current_time,
            user_id=user_id,
            team_id=team_id,
            analysis_type=analysis_type,
            credits_used=credits_used,
            agent_name=agent_name,
            success=success,
            metadata=enhanced_metadata
        )
        
        # Add to history
        self.usage_history.append(usage)
        
        # Update usage summaries
        date_key = datetime.fromtimestamp(current_time).strftime("%Y-%m-%d")
        week_key = datetime.fromtimestamp(current_time).strftime("%Y-W%U")
        month_key = datetime.fromtimestamp(current_time).strftime("%Y-%m")
        
        self.daily_usage[date_key][user_id] += credits_used
        self.daily_usage[date_key][team_id] += credits_used
        
        self.weekly_usage[week_key][user_id] += credits_used
        self.weekly_usage[week_key][team_id] += credits_used
        
        self.monthly_usage[month_key][user_id] += credits_used
        self.monthly_usage[month_key][team_id] += credits_used
        
        # Save to file
        self._save_usage_record(usage)
        
        if bypass_limits:
            logger.info(f"Tracked usage (bypass limits): {credits_used} credits for {analysis_type} by {user_id}/{team_id}")
        else:
            logger.debug(f"Tracked usage: {credits_used} credits for {analysis_type} by {user_id}/{team_id}")
    
    def get_usage_summary(
        self,
        entity_id: str,
        period_days: int = 7
    ) -> UsageSummary:
        """
        Get usage summary for an entity over a time period.
        
        Args:
            entity_id: User or team ID
            period_days: Number of days to include in summary
            
        Returns:
            Usage summary with analytics
        """
        current_time = time.time()
        period_start = current_time - (period_days * 24 * 3600)
        
        # Filter usage records
        relevant_usage = [
            usage for usage in self.usage_history
            if (usage.user_id == entity_id or usage.team_id == entity_id) and
               usage.timestamp >= period_start
        ]
        
        # Calculate summary
        total_credits = sum(usage.credits_used for usage in relevant_usage)
        successful_analyses = sum(1 for usage in relevant_usage if usage.success)
        failed_analyses = sum(1 for usage in relevant_usage if not usage.success)
        
        # Analysis type breakdown
        analysis_breakdown = defaultdict(int)
        for usage in relevant_usage:
            analysis_breakdown[usage.analysis_type] += usage.credits_used
        
        # Agent breakdown
        agent_breakdown = defaultdict(int)
        for usage in relevant_usage:
            agent_breakdown[usage.agent_name] += usage.credits_used
        
        # Hourly usage pattern
        hourly_usage = [0] * 24
        for usage in relevant_usage:
            hour = datetime.fromtimestamp(usage.timestamp).hour
            hourly_usage[hour] += usage.credits_used
        
        return UsageSummary(
            period_start=period_start,
            period_end=current_time,
            total_credits=total_credits,
            successful_analyses=successful_analyses,
            failed_analyses=failed_analyses,
            analysis_breakdown=dict(analysis_breakdown),
            agent_breakdown=dict(agent_breakdown),
            hourly_usage=hourly_usage
        )
    
    def get_current_usage(self, entity_id: str) -> Dict[str, int]:
        """Get current usage for daily, weekly, and monthly periods."""
        current_time = time.time()
        today = datetime.fromtimestamp(current_time).strftime("%Y-%m-%d")
        this_week = datetime.fromtimestamp(current_time).strftime("%Y-W%U")
        this_month = datetime.fromtimestamp(current_time).strftime("%Y-%m")
        
        return {
            "daily": self.daily_usage[today].get(entity_id, 0),
            "weekly": self.weekly_usage[this_week].get(entity_id, 0),
            "monthly": self.monthly_usage[this_month].get(entity_id, 0)
        }
    
    def get_budget_status(self, entity_id: str) -> Dict[str, Any]:
        """Get budget status and remaining credits for an entity."""
        budget = self.budgets.get(entity_id)
        if not budget:
            return {
                "has_budget": False,
                "entity_id": entity_id
            }
        
        current_usage = self.get_current_usage(entity_id)
        
        return {
            "has_budget": True,
            "entity_id": entity_id,
            "entity_type": budget.entity_type,
            "budget": {
                "daily_limit": budget.daily_limit,
                "weekly_limit": budget.weekly_limit,
                "monthly_limit": budget.monthly_limit,
                "allow_overrun": budget.allow_overrun,
                "overrun_limit": budget.overrun_limit
            },
            "usage": current_usage,
            "remaining": {
                "daily": max(0, budget.daily_limit - current_usage["daily"]),
                "weekly": max(0, budget.weekly_limit - current_usage["weekly"]),
                "monthly": max(0, budget.monthly_limit - current_usage["monthly"])
            },
            "utilization": {
                "daily": min(1.0, current_usage["daily"] / budget.daily_limit),
                "weekly": min(1.0, current_usage["weekly"] / budget.weekly_limit),
                "monthly": min(1.0, current_usage["monthly"] / budget.monthly_limit)
            }
        }
    
    def set_budget(
        self,
        entity_id: str,
        entity_type: str,
        daily_limit: int,
        weekly_limit: int,
        monthly_limit: int,
        priority: int = 1,
        allow_overrun: bool = False,
        overrun_limit: int = 0
    ):
        """Set or update credit budget for an entity."""
        budget = CreditBudget(
            entity_id=entity_id,
            entity_type=entity_type,
            daily_limit=daily_limit,
            weekly_limit=weekly_limit,
            monthly_limit=monthly_limit,
            priority=priority,
            allow_overrun=allow_overrun,
            overrun_limit=overrun_limit
        )
        
        self.budgets[entity_id] = budget
        self._save_budgets()
        
        logger.info(f"Set budget for {entity_id}: daily={daily_limit}, weekly={weekly_limit}, monthly={monthly_limit}")
    
    def get_cost_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive cost analytics for the specified period."""
        summary = self.get_usage_summary("all", days)
        
        # Top consumers
        entity_usage = defaultdict(int)
        for usage in self.usage_history[-1000:]:  # Last 1000 records
            entity_usage[usage.user_id] += usage.credits_used
            entity_usage[usage.team_id] += usage.credits_used
        
        top_consumers = sorted(
            entity_usage.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Cost trends
        daily_totals = defaultdict(int)
        for usage in self.usage_history:
            if usage.timestamp >= summary.period_start:
                date = datetime.fromtimestamp(usage.timestamp).strftime("%Y-%m-%d")
                daily_totals[date] += usage.credits_used
        
        return {
            "period_days": days,
            "total_credits": summary.total_credits,
            "success_rate": summary.success_rate,
            "cost_per_success": summary.cost_per_success,
            "analysis_breakdown": summary.analysis_breakdown,
            "agent_breakdown": summary.agent_breakdown,
            "top_consumers": top_consumers,
            "daily_trends": dict(daily_totals),
            "hourly_pattern": summary.hourly_usage,
            "budget_summary": {
                entity_id: self.get_budget_status(entity_id)
                for entity_id in self.budgets.keys()
            }
        }
    
    def optimize_recommendations(self) -> List[Dict[str, Any]]:
        """Generate cost optimization recommendations based on usage patterns."""
        recommendations = []
        
        analytics = self.get_cost_analytics(30)
        
        # High cost per success
        if analytics["cost_per_success"] > 30:
            recommendations.append({
                "type": "cost_efficiency",
                "priority": "high",
                "title": "High Cost Per Successful Analysis",
                "description": f"Current cost is {analytics['cost_per_success']:.1f} credits per success. Consider improving pattern matching accuracy.",
                "actions": [
                    "Review and enhance RDM pattern database",
                    "Improve regex pattern matching", 
                    "Increase pattern cache hit rate"
                ]
            })
        
        # Low pattern match rate
        pattern_credits = sum(
            credits for analysis_type, credits in analytics["analysis_breakdown"].items()
            if "pattern" in analysis_type
        )
        total_credits = analytics["total_credits"]
        
        if total_credits > 0:
            pattern_rate = pattern_credits / total_credits
            if pattern_rate < 0.6:  # Less than 60% pattern matching
                recommendations.append({
                    "type": "pattern_optimization",
                    "priority": "medium",
                    "title": "Low Pattern Matching Rate",
                    "description": f"Only {pattern_rate:.1%} of analyses use pattern matching. Improve patterns to reduce AI costs.",
                    "actions": [
                        "Add more RDM failure patterns",
                        "Enhance keyword matching",
                        "Review failed pattern matches"
                    ]
                })
        
        # Budget utilization warnings
        for entity_id in self.budgets.keys():
            status = self.get_budget_status(entity_id)
            if status["has_budget"]:
                daily_util = status["utilization"]["daily"]
                if daily_util > 0.8:
                    recommendations.append({
                        "type": "budget_warning",
                        "priority": "high" if daily_util > 0.95 else "medium",
                        "title": f"High Budget Utilization: {entity_id}",
                        "description": f"Daily budget utilization at {daily_util:.1%}. May hit limits soon.",
                        "actions": [
                            "Review analysis priorities",
                            "Increase pattern matching usage",
                            "Consider budget adjustment"
                        ]
                    })
        
        return recommendations