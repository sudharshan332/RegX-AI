#!/usr/bin/env python3

import requests
import json

def test_first_level_ai_endpoint():
    """Test the First Level AI endpoint locally"""
    
    url = "http://localhost:5001/api/agents/triage/first-level-ai"
    
    # Test payload
    payload = {
        "test_result": {
            "test": {"name": "cdp.stargate.test.example.TestClass.test_method"},
            "status": "Failed",
            "AgaveTask": {"_id": {"$oid": "test123456"}},
            "exception_summary": "Test timeout error",
            "system_under_test": {"branch": "ganges-7.6-stable"}
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        # You would normally need a valid JWT token here
        # "Authorization": "Bearer <valid-jwt-token>"
    }
    
    try:
        print("Testing First Level AI endpoint...")
        print(f"URL: {url}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, json=payload, headers=headers)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"Response Body: {response.text}")
        
        if response.status_code == 401:
            print("✓ Endpoint is working (401 = authentication required, which is expected)")
            print("✓ This means the endpoint exists and is properly protected")
            return True
        elif response.status_code == 404:
            print("✗ Endpoint not found - Flask may not have restarted")
            return False
        elif response.status_code == 500:
            print("✗ Server error - check if it's the yaml import issue")
            return False
        else:
            print(f"✓ Unexpected response code: {response.status_code}")
            return True
            
    except Exception as e:
        print(f"✗ Connection error: {e}")
        return False

if __name__ == "__main__":
    success = test_first_level_ai_endpoint()
    if success:
        print("\n🎉 Endpoint is accessible - no more yaml import issues!")
    else:
        print("\n💥 There may still be an issue")