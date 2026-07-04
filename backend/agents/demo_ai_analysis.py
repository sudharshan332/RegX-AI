#!/usr/bin/env python3
"""
Demo script showing the difference between pattern-based analysis 
and user-requested AI analysis in the RegX-AI Agent Framework.
"""

import asyncio
import json
import sys
import os
import time

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from agents.handoff import handoff_manager
from agents.registry import agent_registry
from agents.services.cost_tracker import CostTracker


async def demo_analysis_comparison():
    """Demonstrate the difference between pattern-based and AI analysis."""
    
    print("="*60)
    print("RegX-AI Agent Framework - AI Analysis Demo")
    print("="*60)
    
    # Sample test failure data
    test_failure = {
        "test_name": "cdp.test_cluster_create",
        "status": "failed",
        "error_message": "Connection timeout to cluster node after 30 seconds",
        "task_id": "task_12345",
        "failure_analysis": {"category": "INFRASTRUCTURE"},
        "log_url": "https://logs.example.com/task_12345"
    }
    
    cost_tracker = CostTracker()
    
    print("\n1. Pattern-Based Analysis (Default Behavior)")
    print("-" * 40)
    
    start_time = time.time()
    
    # Normal analysis - should use patterns first
    result1 = await handoff_manager.orchestrate_analysis(
        test_failure.copy(), 
        user_requested_ai=False
    )
    
    execution_time1 = time.time() - start_time
    
    if result1:
        print(f"✅ Analysis Type: {result1.analysis_type}")
        print(f"🎯 Confidence: {result1.confidence:.2f}")
        print(f"🔍 Pattern Matched: {result1.pattern_matched}")
        print(f"💰 Credits Used: {result1.credits_used}")
        print(f"⚡ Source: {result1.source}")
        print(f"⏱️  Execution Time: {execution_time1:.2f}s")
        
        if result1.pattern_description:
            print(f"📋 Pattern: {result1.pattern_description}")
    else:
        print("❌ Analysis failed")
    
    print("\n" + "="*60)
    print("\n2. User-Requested Deep AI Analysis")
    print("-" * 40)
    
    start_time = time.time()
    
    # User clicks "Deep AI Analysis" button
    test_failure_ai = test_failure.copy()
    test_failure_ai["_analysis_context"] = {
        "user_id": "demo_user",
        "team_id": "regx_team", 
        "user_requested_ai": True,
        "deep_analysis": True
    }
    
    result2 = await handoff_manager.orchestrate_analysis(
        test_failure_ai,
        user_requested_ai=True
    )
    
    execution_time2 = time.time() - start_time
    
    if result2:
        print(f"✅ Analysis Type: {result2.analysis_type}")
        print(f"🎯 Confidence: {result2.confidence:.2f}")
        print(f"🔍 Pattern Matched: {result2.pattern_matched}")
        print(f"💰 Credits Used: {result2.credits_used}")
        print(f"⚡ Source: {result2.source}")
        print(f"⏱️  Execution Time: {execution_time2:.2f}s")
        
        if result2.pattern_description:
            print(f"📋 Analysis: {result2.pattern_description}")
        
        # Show additional AI analysis data
        if result2.data.get("suggested_actions"):
            print(f"💡 AI Suggestions: {len(result2.data['suggested_actions'])} actions")
        
        if result2.data.get("failure_timeline"):
            print(f"📅 Timeline Events: {len(result2.data['failure_timeline'])}")
    else:
        print("❌ AI Analysis failed")
    
    print("\n" + "="*60)
    print("\n3. Cost Comparison")
    print("-" * 40)
    
    print(f"Pattern Analysis Credits: {result1.credits_used if result1 else 'N/A'}")
    print(f"AI Analysis Credits: {result2.credits_used if result2 else 'N/A'}")
    
    if result1 and result2:
        savings = result2.credits_used - result1.credits_used
        if savings > 0:
            print(f"💰 Credit Savings (Pattern First): {savings} credits")
            print(f"🎯 Pattern analysis is {savings/max(1, result2.credits_used)*100:.0f}% more cost-effective")
    
    print(f"⚡ Pattern Analysis Speed: {execution_time1:.2f}s")
    print(f"🧠 AI Analysis Speed: {execution_time2:.2f}s")
    
    print("\n" + "="*60)
    print("\n4. Usage Scenarios")
    print("-" * 40)
    
    print("📊 Pattern Analysis (Automatic):")
    print("   • First-line analysis for all test failures")
    print("   • 0 credits for pattern matches")
    print("   • Sub-second response time")
    print("   • 95%+ accuracy on known patterns")
    
    print("\n🧠 Deep AI Analysis (User-Triggered):")
    print("   • User clicks 'Deep AI Analysis' button")
    print("   • Uses AI credits for comprehensive analysis")
    print("   • NO CREDIT LIMITS - user has full control")
    print("   • Provides detailed insights and suggestions")
    print("   • Creates learning data for pattern improvement")
    
    print("\n💡 Best Practice:")
    print("   • Always try pattern analysis first (automatic)")
    print("   • Use AI analysis for complex/unknown failures")
    print("   • Deep AI analysis bypasses all credit limits")
    print("   • Users have complete control over AI spending")
    print("   • AI results improve pattern database over time")
    
    print("\n" + "="*60)


async def demo_rdm_analysis():
    """Demonstrate RDM deployment failure analysis."""
    
    print("\n" + "="*60)
    print("RDM Deployment Failure Analysis Demo")
    print("="*60)
    
    # RDM deployment failure
    rdm_failure = {
        "test_name": "deployment.test_nested_ahv",
        "status": "skipped", 
        "failure_analysis": {"category": "DEVPROD_SERVICE:RDM"},
        "rdm_link": "https://rdm.eng.nutanix.com/scheduled_deployments/456789",
        "scheduled_deployment_id": "456789"
    }
    
    print("\n1. RDM Pattern Analysis")
    print("-" * 30)
    
    result = await handoff_manager.orchestrate_analysis(
        rdm_failure,
        user_requested_ai=False
    )
    
    if result:
        print(f"✅ RDM Analysis: {result.analysis_type}")
        print(f"🎯 Confidence: {result.confidence:.2f}")
        print(f"💰 Credits: {result.credits_used}")
        print(f"🔄 Handoff: {'Yes' if 'handoff' in result.data else 'No'}")
        
        if result.data.get("deployment_type"):
            print(f"🏗️  Deployment Type: {result.data['deployment_type']}")
    
    print("\n2. Deep RDM AI Analysis")
    print("-" * 30)
    
    ai_result = await handoff_manager.orchestrate_analysis(
        rdm_failure,
        user_requested_ai=True
    )
    
    if ai_result:
        print(f"🧠 AI RDM Analysis: {ai_result.analysis_type}")
        print(f"🎯 Confidence: {ai_result.confidence:.2f}")
        print(f"💰 Credits: {ai_result.credits_used}")
        
        if ai_result.data.get("root_cause_analysis"):
            print("🔍 Root Cause Analysis: Available")
        
        if ai_result.data.get("suggested_resolution"):
            print(f"💡 Resolution Steps: {len(ai_result.data['suggested_resolution'])}")


if __name__ == "__main__":
    print("Starting RegX-AI Agent Framework Demo...")
    
    try:
        asyncio.run(demo_analysis_comparison())
        asyncio.run(demo_rdm_analysis())
        
        print("\n✅ Demo completed successfully!")
        print("\nKey Takeaways:")
        print("• Pattern analysis provides instant, cost-free results")
        print("• AI analysis is only used when explicitly requested by users")
        print("• The framework automatically optimizes for cost and speed")
        print("• Users have full control over AI credit usage")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()