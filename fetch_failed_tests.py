#!/usr/bin/env python3
"""
Fetch failed tests for a regression tag using the RegX Flask API.
Usage: python3 fetch_failed_tests.py "master|Full|25Jul2026"
"""

import sys
import requests
import json
import os
from urllib.parse import urlencode

# Configuration
BACKEND_URL = os.environ.get("REGX_BACKEND_URL", "http://10.111.52.90:5001")
AUTH_TOKEN = os.environ.get("REGX_AUTH_TOKEN", "")

def fetch_failed_tests(tag):
    """Fetch failed testcases for a given regression tag."""
    
    # Build the API URL
    params = {
        "tag": tag,
        "include": "basic,exception_summary,intermittent"
    }
    url = f"{BACKEND_URL}/mcp/regression/failed-analysis/analyze?{urlencode(params)}"
    
    # Prepare headers
    headers = {"Content-Type": "application/json"}
    if AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
    
    print(f"Fetching failed tests from: {url}")
    print(f"Using auth token: {'Yes' if AUTH_TOKEN else 'No'}")
    print("-" * 80)
    
    try:
        # Make the request
        response = requests.get(url, headers=headers, verify=False, timeout=60)
        
        # Check response
        if response.status_code == 401:
            print("ERROR: Authentication required. Please provide REGX_AUTH_TOKEN environment variable.")
            print("\nTo get a token:")
            print("1. Log in to the RegX dashboard")
            print("2. Open browser developer tools")
            print("3. Check localStorage for 'regx_auth_token'")
            print("4. Export it: export REGX_AUTH_TOKEN='your-token-here'")
            return None
        
        if response.status_code != 200:
            print(f"ERROR: Backend returned {response.status_code}")
            print(f"Response: {response.text}")
            return None
        
        # Parse response
        data = response.json()
        
        # Extract failed testcases
        results = data.get("results", [])
        
        print(f"\n✓ Successfully fetched {len(results)} failed testcases for tag: {tag}\n")
        
        # Display summary
        print("=" * 80)
        print(f"FAILED TESTCASES SUMMARY")
        print("=" * 80)
        
        for i, test in enumerate(results, 1):
            print(f"\n{i}. {test.get('testcase_name', 'Unknown')}")
            print(f"   ID: {test.get('testcase_id', 'N/A')}")
            print(f"   Failure Stage: {test.get('failure_stage', 'N/A')}")
            print(f"   Exception: {test.get('exception_summary', 'N/A')[:100]}...")
            
            jira_tickets = test.get('jira_tickets', [])
            if jira_tickets:
                print(f"   Jira Tickets: {', '.join(jira_tickets)}")
            
            owner = test.get('regression_owner', 'N/A')
            print(f"   Owner: {owner}")
        
        print("\n" + "=" * 80)
        print(f"Total Failed: {len(results)}")
        print("=" * 80)
        
        return data
    
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out")
        return None
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to backend")
        return None
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_failed_tests.py 'master|Full|25Jul2026'")
        sys.exit(1)
    
    tag = sys.argv[1]
    result = fetch_failed_tests(tag)
    
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
