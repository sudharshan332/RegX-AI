#!/usr/bin/env python3
"""
Fetch failed tests for a regression tag with authentication.
Usage: python3 fetch_failed_tests_with_auth.py "master|Full|25Jul2026" --username YOUR_LDAP_USER
"""

import sys
import requests
import json
import os
import getpass
from urllib.parse import urlencode
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
BACKEND_URL = os.environ.get("REGX_BACKEND_URL", "http://10.111.52.90:5001")

def authenticate(username, password):
    """Authenticate with LDAP and get JWT token."""
    url = f"{BACKEND_URL}/mcp/regression/auth/login"
    
    payload = {
        "username": username,
        "password": password
    }
    
    print(f"Authenticating as {username}...")
    
    try:
        response = requests.post(url, json=payload, verify=False, timeout=10)
        
        if response.status_code != 200:
            print(f"ERROR: Authentication failed ({response.status_code})")
            print(f"Response: {response.text}")
            return None
        
        data = response.json()
        token = data.get("token")
        user = data.get("user", {})
        
        print(f"✓ Authenticated successfully as {user.get('displayName', username)}")
        return token
    
    except Exception as e:
        print(f"ERROR: Authentication failed - {str(e)}")
        return None

def fetch_failed_tests(tag, token):
    """Fetch failed testcases for a given regression tag."""
    
    # Build the API URL
    params = {
        "tag": tag,
        "include": "basic,exception_summary,intermittent"
    }
    url = f"{BACKEND_URL}/mcp/regression/failed-analysis/analyze?{urlencode(params)}"
    
    # Prepare headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    print(f"\nFetching failed tests for tag: {tag}")
    print("-" * 80)
    
    try:
        # Make the request
        response = requests.get(url, headers=headers, verify=False, timeout=120)
        
        if response.status_code != 200:
            print(f"ERROR: Backend returned {response.status_code}")
            print(f"Response: {response.text[:500]}")
            return None
        
        # Parse response
        data = response.json()
        
        # Extract failed testcases
        results = data.get("results", [])
        
        print(f"\n✓ Successfully fetched {len(results)} failed testcases\n")
        
        # Display summary
        print("=" * 80)
        print(f"FAILED TESTCASES FOR TAG: {tag}")
        print("=" * 80)
        
        if not results:
            print("\nNo failed testcases found for this tag.")
            return data
        
        for i, test in enumerate(results, 1):
            print(f"\n{i}. {test.get('testcase_name', 'Unknown')}")
            print(f"   ID: {test.get('testcase_id', 'N/A')}")
            print(f"   Task ID: {test.get('task_id', 'N/A')}")
            print(f"   Failure Stage: {test.get('failure_stage', 'N/A')}")
            
            exception = test.get('exception_summary', 'N/A')
            if exception and exception != 'N/A':
                print(f"   Exception: {exception[:150]}...")
            
            jira_tickets = test.get('jira_tickets', [])
            if jira_tickets:
                print(f"   Jira Tickets: {', '.join(jira_tickets)}")
            
            owner = test.get('regression_owner', 'N/A')
            print(f"   Owner: {owner}")
            
            triage = test.get('triage_category', 'N/A')
            print(f"   Triage: {triage}")
        
        print("\n" + "=" * 80)
        print(f"Total Failed Testcases: {len(results)}")
        print("=" * 80)
        
        # Save to file
        output_file = f"failed_tests_{tag.replace('|', '_')}.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nFull results saved to: {output_file}")
        
        return data
    
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out (this might be a large dataset)")
        return None
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to backend")
        return None
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Fetch failed tests from RegX")
    parser.add_argument("tag", help="Regression tag (e.g., master|Full|25Jul2026)")
    parser.add_argument("--username", "-u", help="LDAP username", required=False)
    parser.add_argument("--token", "-t", help="Pre-existing JWT token", required=False)
    
    args = parser.parse_args()
    
    token = args.token
    
    if not token:
        # Need to authenticate
        username = args.username or os.environ.get("USER") or input("LDAP username: ")
        password = getpass.getpass(f"LDAP password for {username}: ")
        
        token = authenticate(username, password)
        if not token:
            print("\nAuthentication failed. Exiting.")
            sys.exit(1)
    
    # Fetch failed tests
    result = fetch_failed_tests(args.tag, token)
    
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
