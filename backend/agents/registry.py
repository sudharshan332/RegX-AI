"""
Agent registry for managing and coordinating RegX-AI agents.

Provides centralized registration, discovery, health monitoring, and load balancing
for all agent instances in the system.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Type, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
import os
import glob

from .base import BaseAgent, AgentConfig, AnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class AgentHealth:
    """Health status for an agent instance."""
    agent_name: str
    is_healthy: bool = True
    last_check: float = field(default_factory=time.time)
    error_count: int = 0
    last_error: Optional[str] = None
    uptime_seconds: float = 0
    
    def update_health(self, success: bool, error: Optional[str] = None):
        """Update health status based on operation result."""
        self.last_check = time.time()
        
        if success:
            self.error_count = max(0, self.error_count - 1)  # Reduce error count on success
            self.is_healthy = True
        else:
            self.error_count += 1
            self.last_error = error
            # Mark unhealthy after 5 consecutive errors
            if self.error_count >= 5:
                self.is_healthy = False


class AgentRegistry:
    """
    Central registry for all RegX-AI agents.
    
    Manages agent lifecycle, health monitoring, load balancing, and coordination
    between different agent instances.
    """
    
    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {}
        self.agent_types: Dict[str, List[BaseAgent]] = {}
        self.agent_health: Dict[str, AgentHealth] = {}
        self.config_dir = "/Users/sudharshan.musali/regx/RegX-AI/backend/agents/config"
        self.is_running = False
        self.health_check_interval = 30  # seconds
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        logger.info("Agent registry initialized")
    
    def register_agent(self, agent: BaseAgent) -> bool:
        """
        Register a new agent instance.
        
        Args:
            agent: Agent instance to register
            
        Returns:
            True if registration successful
        """
        try:
            agent_name = agent.config.name
            agent_type = agent.config.type
            
            if agent_name in self.agents:
                logger.warning(f"Agent {agent_name} already registered, replacing")
            
            self.agents[agent_name] = agent
            
            # Add to type mapping
            if agent_type not in self.agent_types:
                self.agent_types[agent_type] = []
            self.agent_types[agent_type].append(agent)
            
            # Initialize health tracking
            self.agent_health[agent_name] = AgentHealth(agent_name=agent_name)
            
            logger.info(f"Registered agent: {agent_name} (type: {agent_type})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register agent {agent.config.name}: {e}")
            return False
    
    def unregister_agent(self, agent_name: str) -> bool:
        """
        Unregister an agent instance.
        
        Args:
            agent_name: Name of agent to unregister
            
        Returns:
            True if unregistration successful
        """
        try:
            if agent_name not in self.agents:
                logger.warning(f"Agent {agent_name} not found for unregistration")
                return False
            
            agent = self.agents[agent_name]
            agent_type = agent.config.type
            
            # Stop the agent
            agent.stop()
            
            # Remove from registry
            del self.agents[agent_name]
            
            # Remove from type mapping
            if agent_type in self.agent_types:
                self.agent_types[agent_type] = [
                    a for a in self.agent_types[agent_type] 
                    if a.config.name != agent_name
                ]
            
            # Remove health tracking
            if agent_name in self.agent_health:
                del self.agent_health[agent_name]
            
            logger.info(f"Unregistered agent: {agent_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unregister agent {agent_name}: {e}")
            return False
    
    def get_agent(self, agent_name: str) -> Optional[BaseAgent]:
        """Get agent by name."""
        return self.agents.get(agent_name)
    
    def get_agents_by_type(self, agent_type: str) -> List[BaseAgent]:
        """Get all agents of a specific type."""
        return self.agent_types.get(agent_type, [])
    
    def get_healthy_agents_by_type(self, agent_type: str) -> List[BaseAgent]:
        """Get all healthy agents of a specific type."""
        agents = self.get_agents_by_type(agent_type)
        return [
            agent for agent in agents
            if self.agent_health.get(agent.config.name, AgentHealth("")).is_healthy
        ]
    
    def find_capable_agents(self, test_result: Dict[str, Any]) -> List[BaseAgent]:
        """
        Find agents capable of handling a specific test result.
        
        Args:
            test_result: Test result data
            
        Returns:
            List of capable agents, ordered by health and performance
        """
        capable_agents = []
        
        for agent in self.agents.values():
            if agent.can_handle(test_result):
                health = self.agent_health.get(agent.config.name)
                if health and health.is_healthy:
                    capable_agents.append(agent)
        
        # Sort by performance metrics (success rate, execution time)
        capable_agents.sort(
            key=lambda a: (
                -a.metrics.successful_analyses / max(1, a.metrics.total_analyses),
                a.metrics.average_execution_time_ms
            )
        )
        
        return capable_agents
    
    async def analyze_with_best_agent(
        self, 
        test_result: Dict[str, Any], 
        preferred_type: Optional[str] = None,
        user_requested_ai: bool = False
    ) -> Optional[AnalysisResult]:
        """
        Analyze test result using the best available agent.
        
        Args:
            test_result: Test result data
            preferred_type: Preferred agent type (optional)
            
        Returns:
            Analysis result or None if no capable agent found
        """
        try:
            # Find capable agents
            if preferred_type:
                capable_agents = self.get_healthy_agents_by_type(preferred_type)
                capable_agents = [a for a in capable_agents if a.can_handle(test_result)]
            else:
                capable_agents = self.find_capable_agents(test_result)
            
            if not capable_agents:
                logger.warning("No capable agents found for test result")
                return None
            
            # Use the best agent (first in sorted list)
            best_agent = capable_agents[0]
            
            logger.info(f"Using agent {best_agent.config.name} for analysis")
            
            # Perform analysis
            result = await best_agent.analyze(test_result, user_requested_ai)
            
            # Update health based on result
            health = self.agent_health.get(best_agent.config.name)
            if health:
                health.update_health(result.success, result.errors[0] if result.errors else None)
            
            return result
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            # Update health for the agent if we know which one failed
            if 'best_agent' in locals():
                health = self.agent_health.get(best_agent.config.name)
                if health:
                    health.update_health(False, str(e))
            return None
    
    def load_agents_from_config(self) -> int:
        """
        Load agents from configuration files.
        
        Returns:
            Number of agents loaded
        """
        if not os.path.exists(self.config_dir):
            logger.warning(f"Config directory not found: {self.config_dir}")
            return 0
        
        config_files = glob.glob(os.path.join(self.config_dir, "*.yml"))
        loaded_count = 0
        
        for config_file in config_files:
            try:
                config = AgentConfig.from_yaml(config_file)
                agent = self._create_agent_from_config(config)
                
                if agent and self.register_agent(agent):
                    agent.start()
                    loaded_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to load agent from {config_file}: {e}")
        
        logger.info(f"Loaded {loaded_count} agents from configuration files")
        return loaded_count
    
    def _create_agent_from_config(self, config: AgentConfig) -> Optional[BaseAgent]:
        """Create agent instance from configuration."""
        try:
            # Import agent classes
            from .base import SkillWrapperAgent
            from .analysis.cdp_triage_agent import CDPTriageAgent
            from .analysis.rdm_analysis_agent import RDMAnalysisAgent
            from .analysis.intelligent_triage_agent import IntelligentTriageAgent
            
            # Map agent types to classes
            agent_classes = {
                "analysis_agent": SkillWrapperAgent,
                "deployment_agent": SkillWrapperAgent,
                "cdp_triage": CDPTriageAgent,
                "rdm_analysis": RDMAnalysisAgent,
                "intelligent_triage": IntelligentTriageAgent,
            }
            
            agent_class = agent_classes.get(config.type)
            if not agent_class:
                logger.error(f"Unknown agent type: {config.type}")
                return None
            
            return agent_class(config)
            
        except ImportError as e:
            logger.warning(f"Agent class not available for {config.type}: {e}")
            # Fall back to SkillWrapperAgent for skill-based agents
            if config.skill_wrapper:
                from .base import SkillWrapperAgent
                return SkillWrapperAgent(config)
            return None
        except Exception as e:
            logger.error(f"Failed to create agent from config: {e}")
            return None
    
    async def start_health_monitoring(self):
        """Start background health monitoring for all agents."""
        self.is_running = True
        
        while self.is_running:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(self.health_check_interval)
            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(5)  # Short delay on error
    
    async def _perform_health_checks(self):
        """Perform health checks on all registered agents."""
        current_time = time.time()
        
        for agent_name, agent in self.agents.items():
            try:
                health = self.agent_health.get(agent_name)
                if not health:
                    continue
                
                # Update uptime
                health.uptime_seconds = current_time - (health.last_check - health.uptime_seconds)
                
                # Check if agent is responsive
                if not agent.is_active:
                    health.update_health(False, "Agent not active")
                    continue
                
                # Check metrics for signs of issues
                metrics = agent.get_metrics()
                if metrics.total_analyses > 0:
                    success_rate = metrics.successful_analyses / metrics.total_analyses
                    if success_rate < 0.5:  # Less than 50% success rate
                        health.update_health(False, "Low success rate")
                        continue
                
                # Agent appears healthy
                health.update_health(True)
                
            except Exception as e:
                logger.error(f"Health check failed for {agent_name}: {e}")
                if agent_name in self.agent_health:
                    self.agent_health[agent_name].update_health(False, str(e))
    
    def stop_health_monitoring(self):
        """Stop background health monitoring."""
        self.is_running = False
        logger.info("Health monitoring stopped")
    
    def get_registry_status(self) -> Dict[str, Any]:
        """Get overall registry status and metrics."""
        total_agents = len(self.agents)
        healthy_agents = sum(
            1 for health in self.agent_health.values() 
            if health.is_healthy
        )
        
        agent_types_summary = {}
        for agent_type, agents in self.agent_types.items():
            healthy_count = sum(
                1 for agent in agents
                if self.agent_health.get(agent.config.name, AgentHealth("")).is_healthy
            )
            agent_types_summary[agent_type] = {
                "total": len(agents),
                "healthy": healthy_count
            }
        
        return {
            "total_agents": total_agents,
            "healthy_agents": healthy_agents,
            "agent_types": agent_types_summary,
            "health_check_interval": self.health_check_interval,
            "is_monitoring": self.is_running,
            "agents": [
                {
                    "name": agent.config.name,
                    "type": agent.config.type,
                    "active": agent.is_active,
                    "healthy": self.agent_health.get(agent.config.name, AgentHealth("")).is_healthy,
                    "metrics": agent.get_status()["metrics"]
                }
                for agent in self.agents.values()
            ]
        }
    
    def shutdown(self):
        """Shutdown the registry and all agents."""
        logger.info("Shutting down agent registry")
        
        # Stop health monitoring
        self.stop_health_monitoring()
        
        # Stop all agents
        for agent_name in list(self.agents.keys()):
            self.unregister_agent(agent_name)
        
        # Shutdown thread pool
        self.executor.shutdown(wait=True)
        
        logger.info("Agent registry shutdown complete")


# Global registry instance
agent_registry = AgentRegistry()