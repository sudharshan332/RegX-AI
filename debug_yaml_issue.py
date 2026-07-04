#!/usr/bin/env python3

import sys
import os
import asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

def test_first_level_ai():
    """Exactly replicate what the Flask endpoint does."""
    try:
        print("Step 1: Testing imports...")
        
        # Test the exact imports the endpoint uses
        from agents.analysis.intelligent_triage_agent import IntelligentTriageAgent
        from agents.base import AgentConfig
        print("✓ Imports successful")
        
        print("Step 2: Creating agent config...")
        agent_config = AgentConfig(
            name="intelligent_triage",
            type="intelligent_triage"
        )
        print("✓ AgentConfig created")
        
        print("Step 3: Creating IntelligentTriageAgent...")
        agent = IntelligentTriageAgent(agent_config)
        print("✓ IntelligentTriageAgent created")
        
        print("Step 4: Testing analyze method...")
        test_result = {
            "test": {"name": "test.example"},
            "status": "Failed",
            "AgaveTask": {"_id": {"$oid": "test123"}}
        }
        
        async def run_analysis():
            return await agent.analyze(test_result, user_requested_ai=True)
        
        # Create new event loop for the analysis (same as endpoint)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            analysis_result = loop.run_until_complete(run_analysis())
            print("✓ Analysis completed successfully")
            print(f"Result type: {type(analysis_result)}")
        finally:
            loop.close()
            
        print("\n✅ All steps completed successfully - No yaml error!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error occurred: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=== Testing First Level AI Endpoint Logic ===")
    success = test_first_level_ai()
    if success:
        print("\n🎉 Test PASSED - Flask endpoint logic should work")
    else:
        print("\n💥 Test FAILED - There's an issue to fix")