#!/usr/bin/env python3
"""
Agent Framework Integration Script

Initializes and starts the RegX-AI Agent Framework including:
- Loading agent configurations
- Starting the agent registry
- Initializing services (pattern cache, cost tracker)
- Setting up MCP bridge
- Starting health monitoring
"""

import asyncio
import logging
import signal
import sys
import os
import time
from typing import Optional

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from agents.registry import agent_registry
from agents.handoff import handoff_manager
from agents.services.pattern_cache import PatternCache
from agents.services.cost_tracker import CostTracker
from agents.integration.mcp_bridge import MCPBridgeAgent
from agents.base import AgentConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/Users/sudharshan.musali/regx/RegX-AI/backend/agents/data/agent_framework.log')
    ]
)

logger = logging.getLogger(__name__)


class AgentFrameworkManager:
    """Manager for the complete agent framework."""
    
    def __init__(self):
        self.running = False
        self.pattern_cache = PatternCache()
        self.cost_tracker = CostTracker()
        self.mcp_bridge = None
        
    async def initialize(self):
        """Initialize the agent framework."""
        try:
            logger.info("Initializing RegX-AI Agent Framework...")
            
            # Step 1: Load agent configurations
            logger.info("Loading agent configurations...")
            loaded_count = agent_registry.load_agents_from_config()
            logger.info(f"Loaded {loaded_count} agent configurations")
            
            # Step 2: Create and register MCP bridge agent
            logger.info("Initializing MCP bridge...")
            mcp_config = AgentConfig(
                name="mcp-bridge-main",
                type="mcp_bridge",
                cost_optimization={
                    "enable_caching": True,
                    "session_max_age": 3600,
                    "max_concurrent_calls": 10
                }
            )
            
            self.mcp_bridge = MCPBridgeAgent(mcp_config)
            agent_registry.register_agent(self.mcp_bridge)
            self.mcp_bridge.start()
            
            # Step 3: Start health monitoring
            logger.info("Starting health monitoring...")
            asyncio.create_task(agent_registry.start_health_monitoring())
            
            # Step 4: Initialize services
            logger.info("Initializing pattern cache and cost tracker...")
            pattern_stats = self.pattern_cache.get_pattern_stats()
            logger.info(f"Pattern cache initialized with {pattern_stats['total_patterns']} patterns")
            
            # Step 5: Set up default budgets
            self._setup_default_budgets()
            
            logger.info("Agent framework initialization complete")
            
        except Exception as e:
            logger.error(f"Failed to initialize agent framework: {e}")
            raise
    
    def _setup_default_budgets(self):
        """Set up default credit budgets."""
        try:
            # Default team budgets
            teams_budgets = [
                {
                    "entity_id": "regx_team",
                    "entity_type": "team", 
                    "daily_limit": 500,
                    "weekly_limit": 2000,
                    "monthly_limit": 8000
                },
                {
                    "entity_id": "cdp_team",
                    "entity_type": "team",
                    "daily_limit": 300,
                    "weekly_limit": 1500, 
                    "monthly_limit": 6000
                },
                {
                    "entity_id": "system",
                    "entity_type": "user",
                    "daily_limit": 200,
                    "weekly_limit": 1000,
                    "monthly_limit": 4000
                }
            ]
            
            for budget_config in teams_budgets:
                self.cost_tracker.set_budget(**budget_config)
                logger.info(f"Set budget for {budget_config['entity_id']}")
                
        except Exception as e:
            logger.warning(f"Failed to set up default budgets: {e}")
    
    async def start(self):
        """Start the agent framework."""
        try:
            await self.initialize()
            
            self.running = True
            logger.info("RegX-AI Agent Framework started successfully")
            
            # Print startup summary
            self.print_startup_summary()
            
            # Keep the framework running
            while self.running:
                await asyncio.sleep(10)
                await self.health_check()
                
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Agent framework error: {e}")
        finally:
            await self.shutdown()
    
    async def health_check(self):
        """Perform periodic health checks."""
        try:
            status = agent_registry.get_registry_status()
            
            # Log warnings for unhealthy agents
            if status["healthy_agents"] < status["total_agents"]:
                unhealthy_count = status["total_agents"] - status["healthy_agents"]
                logger.warning(f"{unhealthy_count} agents are unhealthy")
            
            # Check cost usage
            analytics = self.cost_tracker.get_cost_analytics(1)  # Last day
            if analytics["total_credits"] > 1000:  # High usage threshold
                logger.warning(f"High credit usage detected: {analytics['total_credits']} credits in last day")
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
    
    def print_startup_summary(self):
        """Print startup summary."""
        status = agent_registry.get_registry_status()
        pattern_stats = self.pattern_cache.get_pattern_stats()
        
        print("\n" + "="*60)
        print("         RegX-AI Agent Framework Started")
        print("="*60)
        print(f"Agents:           {status['healthy_agents']}/{status['total_agents']} healthy")
        print(f"Pattern Cache:    {pattern_stats['total_patterns']} patterns loaded")
        print(f"MCP Servers:      {len(self.mcp_bridge.servers) if self.mcp_bridge else 0} configured")
        print(f"Cost Tracking:    {len(self.cost_tracker.budgets)} budgets configured")
        print(f"Handoff Rules:    {len(handoff_manager.handoff_rules)} rules loaded")
        
        print("\nAgent Types:")
        for agent_type, agents in status["agent_types"].items():
            print(f"  {agent_type}: {agents['healthy']}/{agents['total']}")
        
        print(f"\nLog File: /Users/sudharshan.musali/regx/RegX-AI/backend/agents/data/agent_framework.log")
        print("="*60 + "\n")
    
    async def shutdown(self):
        """Shutdown the agent framework."""
        logger.info("Shutting down agent framework...")
        
        try:
            self.running = False
            
            # Stop health monitoring
            agent_registry.stop_health_monitoring()
            
            # Shutdown agents
            agent_registry.shutdown()
            
            # Clear caches
            if self.pattern_cache:
                self.pattern_cache.clear_cache()
            
            if self.mcp_bridge:
                self.mcp_bridge.clear_cache()
            
            logger.info("Agent framework shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


async def test_framework():
    """Test the agent framework with sample data."""
    logger.info("Running agent framework tests...")
    
    try:
        # Test pattern matching
        test_result = {
            "test_name": "cdp.test_cluster_create", 
            "status": "failed",
            "error_message": "Connection timeout to cluster",
            "failure_analysis": {"category": "INFRASTRUCTURE"}
        }
        
        # Test orchestrated analysis
        result = await handoff_manager.orchestrate_analysis(test_result)
        
        if result.success:
            logger.info(f"Test analysis successful: {result.analysis_type} (confidence: {result.confidence:.2f})")
        else:
            logger.warning(f"Test analysis failed: {result.errors}")
        
        # Test MCP bridge
        if agent_registry.get_agents_by_type("mcp_bridge"):
            mcp_agent = agent_registry.get_agents_by_type("mcp_bridge")[0]
            mcp_status = mcp_agent.get_server_status()
            logger.info(f"MCP bridge status: {mcp_status['total_servers']} servers, {mcp_status['active_sessions']} sessions")
        
        # Test cost tracking
        framework_manager = AgentFrameworkManager()
        analytics = framework_manager.cost_tracker.get_cost_analytics(1)
        logger.info(f"Cost analytics: {analytics['total_credits']} credits, {analytics['success_rate']:.2f} success rate")
        
        logger.info("Agent framework tests completed successfully")
        
    except Exception as e:
        logger.error(f"Framework test failed: {e}")


def setup_signal_handlers(framework_manager):
    """Set up signal handlers for graceful shutdown."""
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        framework_manager.running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="RegX-AI Agent Framework")
    parser.add_argument("--test", action="store_true", help="Run tests instead of starting framework")
    parser.add_argument("--config-dir", help="Configuration directory path")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    
    args = parser.parse_args()
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))
    
    if args.test:
        await test_framework()
    else:
        framework_manager = AgentFrameworkManager()
        setup_signal_handlers(framework_manager)
        
        try:
            await framework_manager.start()
        except Exception as e:
            logger.error(f"Framework failed to start: {e}")
            return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)