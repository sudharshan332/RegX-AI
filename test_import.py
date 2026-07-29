#!/usr/bin/env python3

# Test if our imports work correctly
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

try:
    from agents.analysis.intelligent_triage_agent import IntelligentTriageAgent
    from agents.base import AgentConfig
    print("✓ Imports successful")
    
    # Test if we can create the config and agent
    agent_config = AgentConfig(
        name="intelligent_triage",
        type="intelligent_triage"
    )
    print("✓ AgentConfig created successfully")
    
    agent = IntelligentTriageAgent(agent_config)
    print("✓ IntelligentTriageAgent created successfully")
    
    print("✓ All imports and initializations work correctly")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()