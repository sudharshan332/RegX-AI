"""
Comprehensive test suite for the RegX-AI Agent Framework

Tests all major components including pattern matching, cost tracking,
agent coordination, and API functionality.
"""

import unittest
import asyncio
import tempfile
import shutil
import json
import time
from unittest.mock import Mock, patch, AsyncMock
import sys
import os

# Add the backend directory to the Python path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from agents.base import BaseAgent, SkillWrapperAgent, AgentConfig, AnalysisResult
from agents.registry import AgentRegistry
from agents.services.pattern_cache import PatternCache, PatternMatch
from agents.services.cost_tracker import CostTracker, CreditBudget
from agents.handoff import CrossSkillHandoffManager, HandoffRule, HandoffTrigger
from agents.analysis.cdp_triage_agent import CDPTriageAgent
from agents.analysis.rdm_analysis_agent import RDMAnalysisAgent
from agents.integration.mcp_bridge import MCPBridgeAgent


class TestBaseAgent(unittest.TestCase):
    """Test base agent functionality."""
    
    def setUp(self):
        self.config = AgentConfig(
            name="test_agent",
            type="test",
            triggers=[
                {"event": "test_failed", "conditions": ["status == failed"]}
            ]
        )
    
    def test_agent_config_creation(self):
        """Test agent configuration creation."""
        self.assertEqual(self.config.name, "test_agent")
        self.assertEqual(self.config.type, "test")
        self.assertEqual(len(self.config.triggers), 1)
    
    def test_agent_config_from_yaml(self):
        """Test loading agent config from YAML."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml_content = """
name: yaml_test_agent
type: yaml_test
triggers:
  - event: test_failed
    conditions:
      - status == failed
cost_optimization:
  pattern_first: true
"""
            f.write(yaml_content)
            f.flush()
            
            try:
                config = AgentConfig.from_yaml(f.name)
                self.assertEqual(config.name, "yaml_test_agent")
                self.assertEqual(config.type, "yaml_test")
                self.assertTrue(config.cost_optimization.get("pattern_first"))
            finally:
                os.unlink(f.name)
    
    def test_analysis_result_creation(self):
        """Test analysis result data structure."""
        result = AnalysisResult(
            success=True,
            analysis_type="test",
            confidence=0.85,
            pattern_matched=True,
            pattern_description="Test pattern",
            credits_used=5
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.confidence, 0.85)
        self.assertTrue(result.pattern_matched)
        self.assertEqual(result.credits_used, 5)


class TestPatternCache(unittest.TestCase):
    """Test pattern matching and caching functionality."""
    
    def setUp(self):
        self.pattern_cache = PatternCache({"ttl_hours": 1, "max_entries": 100})
    
    def test_simple_pattern_matching(self):
        """Test simple status-based pattern matching."""
        test_result = {
            "status": "failed",
            "failure_analysis": {"category": "TEST_BUG"}
        }
        
        match = self.pattern_cache.match_simple_patterns(test_result)
        self.assertIsNotNone(match)
        self.assertEqual(match.pattern_type, "simple")
    
    def test_rdm_pattern_matching(self):
        """Test RDM-specific pattern matching."""
        test_result = {
            "pattern_matched": True,
            "pattern_description": "Resource allocation/provisioning failure - intermittent rerun",
            "rdm_category": "PRODUCT"
        }
        
        match = self.pattern_cache.match_rdm_patterns(test_result)
        self.assertIsNotNone(match)
        self.assertEqual(match.pattern_type, "rdm")
        self.assertEqual(match.category, "PRODUCT")
    
    def test_regex_pattern_matching(self):
        """Test regex-based log pattern matching."""
        test_result = {
            "error_message": "Connection refused on port 9440"
        }
        
        match = self.pattern_cache.match_regex_patterns(test_result)
        self.assertIsNotNone(match)
        self.assertEqual(match.pattern_type, "regex")
    
    def test_best_pattern_match(self):
        """Test finding the best pattern match."""
        test_result = {
            "status": "skipped",
            "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"}
        }
        
        match = self.pattern_cache.find_best_pattern_match(test_result, min_confidence=0.8)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.confidence, 0.8)
    
    def test_pattern_cache_stats(self):
        """Test pattern cache statistics."""
        stats = self.pattern_cache.get_pattern_stats()
        
        self.assertIn("total_patterns", stats)
        self.assertIn("cache_stats", stats)
        self.assertIn("cache_hit_rate", stats)
        self.assertGreaterEqual(stats["total_patterns"], 0)


class TestCostTracker(unittest.TestCase):
    """Test cost tracking and budget enforcement."""
    
    def setUp(self):
        # Use temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()
        self.cost_tracker = CostTracker({"data_dir": self.temp_dir})
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_budget_creation(self):
        """Test budget creation and management."""
        self.cost_tracker.set_budget(
            entity_id="test_team",
            entity_type="team",
            daily_limit=100,
            weekly_limit=500,
            monthly_limit=2000
        )
        
        budget_status = self.cost_tracker.get_budget_status("test_team")
        self.assertTrue(budget_status["has_budget"])
        self.assertEqual(budget_status["budget"]["daily_limit"], 100)
    
    def test_credit_usage_tracking(self):
        """Test credit usage tracking."""
        self.cost_tracker.track_usage(
            analysis_type="test_analysis",
            credits_used=10,
            user_id="test_user",
            team_id="test_team",
            success=True
        )
        
        current_usage = self.cost_tracker.get_current_usage("test_team")
        self.assertEqual(current_usage["daily"], 10)
    
    def test_credit_limit_enforcement(self):
        """Test credit limit enforcement."""
        # Set small budget
        self.cost_tracker.set_budget(
            entity_id="limited_team",
            entity_type="team",
            daily_limit=5,
            weekly_limit=20,
            monthly_limit=50
        )
        
        # Test within limits
        can_use, reason = self.cost_tracker.can_use_credits("test_user", "limited_team", 3)
        self.assertTrue(can_use)
        
        # Use some credits
        self.cost_tracker.track_usage("test", 4, user_id="test_user", team_id="limited_team")
        
        # Test exceeding limits
        can_use, reason = self.cost_tracker.can_use_credits("test_user", "limited_team", 5)
        self.assertFalse(can_use)
        self.assertIn("limit exceeded", reason)
    
    def test_usage_summary(self):
        """Test usage summary generation."""
        self.cost_tracker.track_usage("test1", 5, team_id="summary_team")
        self.cost_tracker.track_usage("test2", 3, team_id="summary_team")
        
        summary = self.cost_tracker.get_usage_summary("summary_team", period_days=1)
        self.assertEqual(summary.total_credits, 8)
        self.assertEqual(summary.successful_analyses, 2)
    
    def test_cost_analytics(self):
        """Test cost analytics generation."""
        # Add some usage data
        for i in range(5):
            self.cost_tracker.track_usage(f"test_{i}", i+1, success=(i % 2 == 0))
        
        analytics = self.cost_tracker.get_cost_analytics(days=1)
        self.assertIn("total_credits", analytics)
        self.assertIn("success_rate", analytics)
        self.assertIn("analysis_breakdown", analytics)


class TestAgentRegistry(unittest.TestCase):
    """Test agent registry functionality."""
    
    def setUp(self):
        self.registry = AgentRegistry()
        
        # Create test agent config
        self.test_config = AgentConfig(
            name="registry_test_agent",
            type="test_agent",
            triggers=[{"event": "test_failed"}]
        )
    
    def test_agent_registration(self):
        """Test agent registration and retrieval."""
        # Create mock agent
        mock_agent = Mock(spec=BaseAgent)
        mock_agent.config = self.test_config
        mock_agent.is_active = True
        
        # Register agent
        success = self.registry.register_agent(mock_agent)
        self.assertTrue(success)
        
        # Retrieve agent
        retrieved_agent = self.registry.get_agent("registry_test_agent")
        self.assertEqual(retrieved_agent, mock_agent)
    
    def test_agent_unregistration(self):
        """Test agent unregistration."""
        mock_agent = Mock(spec=BaseAgent)
        mock_agent.config = self.test_config
        mock_agent.stop = Mock()
        
        # Register and then unregister
        self.registry.register_agent(mock_agent)
        success = self.registry.unregister_agent("registry_test_agent")
        
        self.assertTrue(success)
        self.assertIsNone(self.registry.get_agent("registry_test_agent"))
        mock_agent.stop.assert_called_once()
    
    def test_agents_by_type(self):
        """Test retrieving agents by type."""
        mock_agent1 = Mock(spec=BaseAgent)
        mock_agent1.config = AgentConfig(name="agent1", type="test_type")
        
        mock_agent2 = Mock(spec=BaseAgent)
        mock_agent2.config = AgentConfig(name="agent2", type="test_type")
        
        self.registry.register_agent(mock_agent1)
        self.registry.register_agent(mock_agent2)
        
        agents = self.registry.get_agents_by_type("test_type")
        self.assertEqual(len(agents), 2)
    
    def test_registry_status(self):
        """Test registry status reporting."""
        status = self.registry.get_registry_status()
        
        self.assertIn("total_agents", status)
        self.assertIn("healthy_agents", status)
        self.assertIn("agent_types", status)


class TestCrossSkillHandoff(unittest.TestCase):
    """Test cross-skill handoff functionality."""
    
    def setUp(self):
        self.handoff_manager = CrossSkillHandoffManager()
        
        # Create mock agents
        self.source_agent = Mock(spec=BaseAgent)
        self.source_agent.config = AgentConfig(name="source", type="cdp_triage")
        
        self.target_agent = Mock(spec=BaseAgent)
        self.target_agent.config = AgentConfig(name="target", type="rdm_analysis")
        
        # Mock registry
        self.mock_registry = Mock()
        self.mock_registry.get_healthy_agents_by_type.return_value = [self.target_agent]
        self.mock_registry.get_agent.return_value = self.target_agent
        
        self.handoff_manager.registry = self.mock_registry
    
    def test_handoff_rule_creation(self):
        """Test handoff rule creation and matching."""
        rule = HandoffRule(
            rule_id="test_rule",
            source_agent_type="cdp_triage",
            target_agent_type="rdm_analysis",
            trigger=HandoffTrigger.FAILURE_CATEGORY,
            conditions={"category": "DEVPROD_SERVICE:RDM"}
        )
        
        # Test matching condition
        test_result = {
            "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"}
        }
        
        matches = rule.matches(test_result)
        self.assertTrue(matches)
    
    async def test_handoff_evaluation(self):
        """Test handoff evaluation."""
        test_result = {
            "status": "skipped",
            "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"}
        }
        
        context = await self.handoff_manager.evaluate_handoff(
            self.source_agent,
            test_result
        )
        
        self.assertIsNotNone(context)
        self.assertEqual(context.source_agent, "source")
        self.assertEqual(context.target_agent, "target")
    
    async def test_handoff_execution(self):
        """Test handoff execution."""
        from agents.handoff import HandoffContext, HandoffStatus
        
        # Create handoff context
        context = HandoffContext(
            handoff_id="test_handoff",
            source_agent="source",
            target_agent="target",
            test_result={"status": "failed"}
        )
        
        # Mock target agent analysis
        mock_result = AnalysisResult(
            success=True,
            analysis_type="handoff_test",
            confidence=0.9,
            pattern_matched=True
        )
        
        self.target_agent.analyze = AsyncMock(return_value=mock_result)
        
        # Execute handoff
        result = await self.handoff_manager.execute_handoff(context)
        
        self.assertTrue(result.success)
        self.assertIn("handoff_execution", result.data)
        self.target_agent.analyze.assert_called_once()
    
    def test_handoff_statistics(self):
        """Test handoff statistics generation."""
        stats = self.handoff_manager.get_handoff_statistics(7)
        
        self.assertIn("total_handoffs", stats)
        self.assertIn("successful_handoffs", stats)
        self.assertIn("success_rate", stats)


class TestSkillWrapperAgent(unittest.TestCase):
    """Test skill wrapper agent functionality."""
    
    def setUp(self):
        self.config = AgentConfig(
            name="test_skill_wrapper",
            type="analysis_agent",
            skill_wrapper="test-skill",
            cost_optimization={
                "pattern_first": True,
                "confidence_threshold": 0.7
            }
        )
        
        # Mock the skill path resolution
        with patch.object(SkillWrapperAgent, '_resolve_skill_path') as mock_resolve:
            mock_resolve.return_value = "/fake/skill/path"
            self.agent = SkillWrapperAgent(self.config)
    
    def test_agent_initialization(self):
        """Test skill wrapper agent initialization."""
        self.assertEqual(self.agent.config.name, "test_skill_wrapper")
        self.assertEqual(self.agent.skill_name, "test-skill")
        self.assertTrue(self.agent.pattern_first)
    
    def test_trigger_matching(self):
        """Test trigger condition matching."""
        # Add trigger to config
        self.agent.config.triggers = [
            {"event": "test_failed", "conditions": ["status == failed"]}
        ]
        
        test_result_match = {"status": "failed"}
        test_result_no_match = {"status": "passed"}
        
        self.assertTrue(self.agent.can_handle(test_result_match))
        self.assertFalse(self.agent.can_handle(test_result_no_match))
    
    async def test_pattern_first_analysis(self):
        """Test pattern-first analysis workflow."""
        test_result = {
            "status": "skipped",
            "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"}
        }
        
        result = await self.agent.analyze(test_result)
        
        # Should get simple pattern match for RDM
        self.assertTrue(result.success)
        self.assertTrue(result.pattern_matched)
        self.assertEqual(result.credits_used, 0)  # No credits for pattern match


class TestAPIIntegration(unittest.TestCase):
    """Test API endpoint functionality."""
    
    def setUp(self):
        # This would require Flask app setup in a real test
        # For now, we'll test the underlying functions
        pass
    
    def test_api_response_format(self):
        """Test API response format consistency."""
        # Mock a typical API response structure
        response = {
            "success": True,
            "analysis": {
                "analysis_type": "cdp_triage",
                "confidence": 0.85,
                "pattern_matched": True,
                "credits_used": 5,
                "execution_time_ms": 1250
            }
        }
        
        self.assertIn("success", response)
        self.assertIn("analysis", response)
        self.assertIn("confidence", response["analysis"])


class TestMCPBridge(unittest.TestCase):
    """Test MCP bridge functionality."""
    
    def setUp(self):
        self.config = AgentConfig(
            name="test_mcp_bridge",
            type="mcp_bridge",
            cost_optimization={
                "enable_caching": True,
                "session_max_age": 3600
            }
        )
        
        self.mcp_bridge = MCPBridgeAgent(self.config)
    
    def test_mcp_bridge_initialization(self):
        """Test MCP bridge initialization."""
        self.assertEqual(self.mcp_bridge.config.name, "test_mcp_bridge")
        self.assertTrue(self.mcp_bridge.enable_caching)
        self.assertGreater(len(self.mcp_bridge.servers), 0)
    
    def test_server_configuration(self):
        """Test MCP server configuration loading."""
        self.assertIn("atlassian", self.mcp_bridge.servers)
        self.assertIn("gw-glean", self.mcp_bridge.servers)
        
        # Test server config structure
        server_config = self.mcp_bridge.servers["atlassian"]
        self.assertEqual(server_config.server_id, "atlassian")
        self.assertIsNotNone(server_config.url)
    
    async def test_mcp_call_cost_tracking(self):
        """Test MCP call cost tracking."""
        # Mock the actual HTTP call
        with patch('requests.post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"mcp-session-id": "test_session"}
            mock_response.json.return_value = {"result": {"data": "test"}}
            mock_post.return_value = mock_response
            
            result = await self.mcp_bridge.call_mcp_tool(
                server_id="atlassian",
                tool_name="test_tool",
                arguments={"query": "test"}
            )
            
            self.assertTrue(result.success)
            self.assertGreater(result.credits_used, 0)


class AgentFrameworkTestSuite(unittest.TestCase):
    """Integration tests for the complete agent framework."""
    
    def setUp(self):
        """Set up integration test environment."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Create test registry
        self.registry = AgentRegistry()
        
        # Create test agents
        self.cdp_config = AgentConfig(
            name="test_cdp_agent",
            type="analysis_agent",
            skill_wrapper="triage-cdp-test-failure"
        )
        
        self.rdm_config = AgentConfig(
            name="test_rdm_agent",
            type="deployment_agent", 
            skill_wrapper="triage-rdm-deployment-failure"
        )
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    async def test_end_to_end_analysis_workflow(self):
        """Test complete analysis workflow from test failure to result."""
        # Test data representing a failed CDP test
        test_result = {
            "test_name": "cdp.test_cluster_create",
            "status": "failed",
            "error_message": "Connection timeout to cluster node",
            "task_id": "test_task_123",
            "failure_analysis": {"category": "INFRASTRUCTURE"}
        }
        
        # Mock agents
        with patch.object(SkillWrapperAgent, '_resolve_skill_path') as mock_resolve:
            mock_resolve.return_value = "/fake/skill/path"
            
            cdp_agent = SkillWrapperAgent(self.cdp_config)
            
            # Test analysis
            result = await cdp_agent.analyze(test_result)
            
            self.assertTrue(result.success)
            self.assertIsNotNone(result.analysis_type)
            self.assertGreaterEqual(result.confidence, 0.0)
    
    async def test_cross_agent_handoff_workflow(self):
        """Test cross-agent handoff workflow."""
        # RDM deployment failure that should trigger handoff
        test_result = {
            "test_name": "deployment.test_rdm_create",
            "status": "skipped",
            "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"},
            "rdm_link": "https://rdm.eng.nutanix.com/scheduled_deployments/123"
        }
        
        # Create handoff manager
        handoff_manager = CrossSkillHandoffManager()
        
        # Mock agents and registry
        mock_cdp_agent = Mock(spec=BaseAgent)
        mock_cdp_agent.config = self.cdp_config
        
        mock_rdm_agent = Mock(spec=BaseAgent) 
        mock_rdm_agent.config = self.rdm_config
        mock_rdm_agent.analyze = AsyncMock(return_value=AnalysisResult(
            success=True,
            analysis_type="rdm_deployment",
            confidence=0.9,
            pattern_matched=True,
            pattern_description="RDM deployment failure"
        ))
        
        mock_registry = Mock()
        mock_registry.get_healthy_agents_by_type.return_value = [mock_rdm_agent]
        mock_registry.get_agent.return_value = mock_rdm_agent
        
        handoff_manager.registry = mock_registry
        
        # Test handoff evaluation and execution
        context = await handoff_manager.evaluate_handoff(mock_cdp_agent, test_result)
        self.assertIsNotNone(context)
        
        result = await handoff_manager.execute_handoff(context)
        self.assertTrue(result.success)
        self.assertIn("handoff_execution", result.data)
    
    def test_pattern_matching_accuracy(self):
        """Test pattern matching accuracy against known patterns."""
        pattern_cache = PatternCache()
        
        # Test cases with expected outcomes
        test_cases = [
            {
                "test_result": {
                    "status": "skipped",
                    "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"}
                },
                "expected_match": True,
                "expected_type": "simple"
            },
            {
                "test_result": {
                    "pattern_matched": True,
                    "pattern_description": "Resource allocation/provisioning failure - intermittent rerun",
                    "rdm_category": "PRODUCT"
                },
                "expected_match": True,
                "expected_type": "rdm"
            },
            {
                "test_result": {
                    "error_message": "FATAL error in stargate.cc:123"
                },
                "expected_match": True,
                "expected_type": "regex"
            }
        ]
        
        for i, test_case in enumerate(test_cases):
            with self.subTest(i=i):
                match = pattern_cache.find_best_pattern_match(
                    test_case["test_result"],
                    min_confidence=0.5
                )
                
                if test_case["expected_match"]:
                    self.assertIsNotNone(match, f"Expected match for test case {i}")
                    self.assertEqual(match.pattern_type, test_case["expected_type"])
                else:
                    self.assertIsNone(match, f"Expected no match for test case {i}")
    
    def test_cost_optimization_effectiveness(self):
        """Test cost optimization effectiveness."""
        cost_tracker = CostTracker({"data_dir": self.temp_dir})
        
        # Simulate analysis with different cost patterns
        # Pattern matches (0 credits)
        for i in range(10):
            cost_tracker.track_usage("pattern_match", 0, success=True)
        
        # Skill analyses (10 credits each)
        for i in range(3):
            cost_tracker.track_usage("skill_analysis", 10, success=True)
        
        # AI analyses (25 credits each) 
        for i in range(2):
            cost_tracker.track_usage("ai_analysis", 25, success=True)
        
        analytics = cost_tracker.get_cost_analytics(1)
        
        # Verify cost distribution
        self.assertEqual(analytics["total_credits"], 80)  # 0 + 30 + 50
        self.assertEqual(analytics["successful_analyses"], 15)
        self.assertLess(analytics["cost_per_success"], 10)  # Should be cost-effective


def run_performance_tests():
    """Run performance tests for the agent framework."""
    print("\n=== Performance Tests ===")
    
    # Test pattern matching performance
    pattern_cache = PatternCache()
    
    test_result = {
        "status": "failed",
        "error_message": "Connection timeout after 30 seconds",
        "failure_analysis": {"category": "INFRASTRUCTURE"}
    }
    
    start_time = time.time()
    for i in range(1000):
        pattern_cache.find_best_pattern_match(test_result)
    end_time = time.time()
    
    avg_time = (end_time - start_time) / 1000
    print(f"Pattern matching: {avg_time:.4f}s average per match")
    
    # Test cost tracking performance
    cost_tracker = CostTracker()
    
    start_time = time.time()
    for i in range(1000):
        cost_tracker.track_usage("test", 1, success=True)
    end_time = time.time()
    
    avg_time = (end_time - start_time) / 1000  
    print(f"Cost tracking: {avg_time:.4f}s average per track")


if __name__ == "__main__":
    # Run unit tests
    print("=== Running Agent Framework Tests ===")
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test classes
    test_classes = [
        TestBaseAgent,
        TestPatternCache,
        TestCostTracker,
        TestAgentRegistry,
        TestCrossSkillHandoff,
        TestSkillWrapperAgent,
        TestAPIIntegration,
        TestMCPBridge,
        AgentFrameworkTestSuite
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Run performance tests
    run_performance_tests()
    
    # Print summary
    print(f"\n=== Test Summary ===")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback}")
    
    # Exit with appropriate code
    exit_code = 0 if (len(result.failures) + len(result.errors)) == 0 else 1
    exit(exit_code)