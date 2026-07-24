#!/usr/bin/env python3
"""
Demo script for Intelligent Triage Analysis in RegX-AI Agent Framework.

Demonstrates the enhanced analysis logic with history-based decisions,
JITA API integration, and Glean search for Nutanix knowledge.
"""

import asyncio
import json
import sys
import os
import time

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from agents.analysis.intelligent_triage_agent import IntelligentTriageAgent
from agents.base import AgentConfig
from agents.integration.mcp_bridge import MCPBridgeAgent


async def demo_failed_test_analysis():
    """Demo analysis of failed testcase with history logic."""
    
    print("="*80)
    print("INTELLIGENT TRIAGE DEMO - Failed Test Analysis")
    print("="*80)
    
    # Create intelligent triage agent
    config = AgentConfig(
        name="demo-intelligent-triage",
        type="intelligent_triage"
    )
    
    agent = IntelligentTriageAgent(config)
    
    # Mock MCP bridge for Glean search
    mcp_config = AgentConfig(name="demo-mcp-bridge", type="mcp_bridge")
    mcp_bridge = MCPBridgeAgent(mcp_config)
    agent.set_mcp_bridge(mcp_bridge)
    
    print("\n1. INTERMITTENT FAILURE SCENARIO")
    print("-" * 50)
    print("Scenario: Test failed but last run was passed (likely intermittent)")
    
    # Test case: Intermittent failure (last run passed)
    intermittent_test = {
        "test_name": "cdp.test_cluster_resilience",
        "status": "failed",
        "task_id": "task_67890",
        "error_message": "Connection timeout during cluster operation",
        "exception_summary": "TimeoutException: Operation timed out after 300 seconds",
        "failure_stage": "execution_stage",
        "log_url": "https://logs.example.com/task_67890"
    }
    
    print(f"Test: {intermittent_test['test_name']}")
    print(f"Status: {intermittent_test['status']}")
    print(f"Error: {intermittent_test['error_message']}")
    
    start_time = time.time()
    result1 = await agent.analyze(intermittent_test)
    execution_time1 = time.time() - start_time
    
    print(f"\n✅ Analysis Complete:")
    print(f"   Type: {result1.analysis_type}")
    print(f"   Confidence: {result1.confidence:.2f}")
    print(f"   Credits: {result1.credits_used}")
    print(f"   Time: {execution_time1:.2f}s")
    print(f"   Source: {result1.source}")
    
    if result1.data.get("first_level_ai"):
        print(f"   🧠 First Level AI: Used")
        print(f"   📊 JITA Analysis: {result1.data.get('jita_analysis', {}).get('success', 'N/A')}")
        print(f"   🔍 Glean Search: {result1.data.get('glean_search', {}).get('found_existing_issue', 'N/A')}")
        
        if result1.data.get("existing_issue_found"):
            tickets = result1.data.get("suggested_tickets", [])
            print(f"   🎫 Suggested Tickets: {len(tickets)}")
    
    print("\n" + "="*80)
    print("\n2. RECURRING FAILURE SCENARIO")
    print("-" * 50)
    print("Scenario: Test consistently fails (pattern matching first)")
    
    # Test case: Recurring failure (should use pattern matching)
    recurring_test = {
        "test_name": "deployment.test_setup_validation",
        "status": "failed", 
        "task_id": "task_12345",
        "error_message": "Setup validation failed: Invalid cluster configuration",
        "exception_summary": "ValidationError: Cluster configuration does not meet requirements",
        "failure_stage": "setup_stage"
    }
    
    print(f"Test: {recurring_test['test_name']}")
    print(f"Status: {recurring_test['status']}")
    print(f"Error: {recurring_test['error_message']}")
    
    start_time = time.time()
    result2 = await agent.analyze(recurring_test)
    execution_time2 = time.time() - start_time
    
    print(f"\n✅ Analysis Complete:")
    print(f"   Type: {result2.analysis_type}")
    print(f"   Confidence: {result2.confidence:.2f}")
    print(f"   Credits: {result2.credits_used}")
    print(f"   Time: {execution_time2:.2f}s")
    print(f"   Pattern Matched: {result2.pattern_matched}")
    
    if result2.pattern_matched:
        print(f"   📋 Pattern: {result2.pattern_description}")
    else:
        print(f"   🧠 First Level AI: Used (no pattern match)")


async def demo_skipped_test_analysis():
    """Demo analysis of skipped testcase with RDM logic."""
    
    print("\n" + "="*80)
    print("INTELLIGENT TRIAGE DEMO - Skipped Test Analysis") 
    print("="*80)
    
    # Create intelligent triage agent
    config = AgentConfig(
        name="demo-intelligent-triage-rdm",
        type="intelligent_triage"
    )
    
    agent = IntelligentTriageAgent(config)
    
    # Mock MCP bridge for Glean search
    mcp_config = AgentConfig(name="demo-mcp-bridge", type="mcp_bridge")
    mcp_bridge = MCPBridgeAgent(mcp_config)
    agent.set_mcp_bridge(mcp_bridge)
    
    print("\n1. RDM PATTERN MATCH SCENARIO")
    print("-" * 50)
    print("Scenario: Skipped test with known RDM pattern")
    
    # Test case: RDM deployment failure with pattern
    rdm_pattern_test = {
        "test_name": "deployment.test_nested_ahv_setup",
        "status": "skipped",
        "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"},
        "rdm_link": "https://rdm.eng.nutanix.com/scheduled_deployments/789123",
        "scheduled_deployment_id": "789123",
        "pattern_matched": True,
        "pattern_description": "Resource allocation/provisioning failure - intermittent rerun",
        "rdm_category": "PRODUCT"
    }
    
    print(f"Test: {rdm_pattern_test['test_name']}")
    print(f"Status: {rdm_pattern_test['status']}")
    print(f"RDM Category: {rdm_pattern_test['failure_analysis']['category']}")
    
    start_time = time.time()
    result1 = await agent.analyze(rdm_pattern_test)
    execution_time1 = time.time() - start_time
    
    print(f"\n✅ Analysis Complete:")
    print(f"   Type: {result1.analysis_type}")
    print(f"   Confidence: {result1.confidence:.2f}")
    print(f"   Credits: {result1.credits_used}")
    print(f"   Time: {execution_time1:.2f}s")
    print(f"   Pattern Matched: {result1.pattern_matched}")
    print(f"   Glean Search: {result1.data.get('existing_issue_found', 'Not performed')}")
    
    if result1.data.get("suggested_tickets"):
        print(f"   🎫 Tickets Found: {len(result1.data['suggested_tickets'])}")
    
    print("\n2. NO PATTERN MATCH SCENARIO")  
    print("-" * 50)
    print("Scenario: Skipped test without known pattern (First Level AI)")
    
    # Test case: Skipped without pattern
    no_pattern_test = {
        "test_name": "deployment.test_custom_config",
        "status": "skipped",
        "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"},
        "rdm_link": "https://rdm.eng.nutanix.com/scheduled_deployments/456789", 
        "error_message": "Custom deployment configuration failed validation",
        "exception_summary": "DeploymentError: Unknown configuration parameter 'custom_network_mode'"
    }
    
    print(f"Test: {no_pattern_test['test_name']}")
    print(f"Status: {no_pattern_test['status']}")
    print(f"Error: {no_pattern_test['error_message']}")
    
    start_time = time.time()
    result2 = await agent.analyze(no_pattern_test)
    execution_time2 = time.time() - start_time
    
    print(f"\n✅ Analysis Complete:")
    print(f"   Type: {result2.analysis_type}")
    print(f"   Confidence: {result2.confidence:.2f}")
    print(f"   Credits: {result2.credits_used}")
    print(f"   Time: {execution_time2:.2f}s")
    print(f"   Source: {result2.source}")
    
    if result2.data.get("first_level_ai"):
        print(f"   🧠 First Level AI: Used")
        print(f"   🔍 Glean Search: Performed")
        print(f"   📚 Nutanix Knowledge: {result2.data.get('nutanix_knowledge', {}).get('total_results', 0)} results")


async def demo_cost_tracking_analytics():
    """Demo cost tracking for analytics (no limits)."""
    
    print("\n" + "="*80)
    print("INTELLIGENT TRIAGE DEMO - Cost Tracking Analytics")
    print("="*80)
    
    print("\n🔍 ANALYSIS TYPE COST BREAKDOWN:")
    print("-" * 50)
    
    analysis_types = [
        ("Pattern Match", "pattern_match", 0),
        ("First Level AI (JITA + Glean)", "first_level_ai_analysis", 15),
        ("RDM Pattern + Glean", "rdm_pattern_with_glean", 5),
        ("Intermittent Analysis", "intermittent_analysis", 15),
        ("Existing Issue Detection", "existing_issue_detection", 5)
    ]
    
    for name, type_id, cost in analysis_types:
        print(f"   {name}: {cost} credits")
    
    print(f"\n💡 KEY INSIGHTS:")
    print(f"   • Pattern matching is FREE (0 credits)")
    print(f"   • First Level AI provides comprehensive analysis")
    print(f"   • Glean search always includes Nutanix knowledge")
    print(f"   • Cost tracking is for ANALYTICS only - NO LIMITS")
    print(f"   • History-based logic optimizes analysis approach")
    
    print(f"\n📊 ANALYSIS FLOW OPTIMIZATION:")
    print(f"   Failed Tests:")
    print(f"      ├── History Check (Free)")
    print(f"      ├── If Intermittent → First Level AI (15 credits)")
    print(f"      └── If Recurring → Pattern Match (0 credits) → AI if needed")
    print(f"   ")
    print(f"   Skipped Tests:")
    print(f"      ├── RDM Pattern Check (Free)")
    print(f"      ├── If Pattern + Glean Search (5 credits)")
    print(f"      └── If No Pattern → First Level AI (15 credits)")
    
    print(f"\n🎯 BENEFITS:")
    print(f"   • Smart routing based on test history")
    print(f"   • Always includes Nutanix knowledge search")
    print(f"   • Existing issue detection and ticket suggestions")
    print(f"   • Pattern learning from AI results")
    print(f"   • Cost tracking for optimization insights")


async def main():
    """Main demo function."""
    
    print("🚀 Starting Intelligent Triage Demo...")
    print("This demonstrates the enhanced analysis logic with:")
    print("• History-based intermittent detection")
    print("• JITA API integration for failure analysis")  
    print("• Glean search for Nutanix knowledge")
    print("• Cost tracking for analytics (no limits)")
    print("• Pattern learning and enhancement")
    
    try:
        await demo_failed_test_analysis()
        await demo_skipped_test_analysis()
        await demo_cost_tracking_analytics()
        
        print("\n" + "="*80)
        print("✅ DEMO COMPLETED SUCCESSFULLY!")
        print("="*80)
        
        print(f"\n🎉 INTELLIGENT TRIAGE FEATURES DEMONSTRATED:")
        print(f"   ✓ History-based analysis routing")
        print(f"   ✓ Intermittent vs recurring failure detection")
        print(f"   ✓ JITA API integration for detailed failure analysis")
        print(f"   ✓ Glean search for Nutanix product knowledge")
        print(f"   ✓ Existing issue detection and ticket suggestions")
        print(f"   ✓ RDM pattern matching with knowledge enhancement")
        print(f"   ✓ Cost tracking for analytics and optimization")
        print(f"   ✓ Pattern learning from AI analysis results")
        
        print(f"\n📈 EXPECTED OUTCOMES:")
        print(f"   • Faster analysis through intelligent routing")
        print(f"   • Better accuracy with Nutanix knowledge integration")
        print(f"   • Proactive issue detection and resolution")
        print(f"   • Continuous pattern improvement from AI learnings")
        print(f"   • Cost optimization through smart analysis selection")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())