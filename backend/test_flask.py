import json
import time
import logging
import requests
import urllib3
import pandas as pd
import os
import glob
import re
import random
import smtplib
import urllib.request
import urllib.error
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict
from io import BytesIO
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, Response, stream_with_context, send_file
from flask_cors import CORS
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ======================================================
# Flask App
# ======================================================
app = Flask(__name__)
CORS(app)

# ======================================================
# Disable SSL warnings
# ======================================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ======================================================
# Logging
# ======================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ======================================================
# Constants
# ======================================================
JITA_BASE = "https://jita.eng.nutanix.com/api/v2"
TRIAGE_GENIE_BASE = "http://triage-genie.eng.nutanix.com/api"
# Login URL for Triage Genie (session auth); override with TRIAGE_GENIE_LOGIN_URL if needed
LOGIN_URL = os.getenv("TRIAGE_GENIE_LOGIN_URL", "http://triage-genie.eng.nutanix.com/login")
PHX_BASE = "https://jita-phx1-webserver-2.eng.nutanix.com/api/v2"
TCMS_BASE = "https://tcms.eng.nutanix.com/api-readonly/v1"

# AI Endpoint for failure summary
AI_BASE = "https://hkn12.ai.nutanix.com/enterpriseai/v1"
AI_API_KEY = "ddb2b793-1004-49a1-b005-4ddf4c2ade8c"

# SSL context for AI endpoint (skip TLS verify)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

MAX_FAILED_TESTS = 50
MAX_WORKERS = 5

HEADERS = {
    "Authorization": "Bearer TOKEN",  # move to env later
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# In-memory storage for manual tasks
# Structure: {tag: {branch: [task_ids]}}
manual_tasks_store = {}

# Run Plan storage file
RUN_PLAN_STORAGE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "run_plans.json")

def load_run_plans():
    """Load run plans from JSON file"""
    try:
        if os.path.exists(RUN_PLAN_STORAGE):
            with open(RUN_PLAN_STORAGE, 'r') as f:
                return json.load(f)
        return {"run_plans": [], "history": []}
    except Exception as e:
        logger.error(f"Error loading run plans: {e}")
        return {"run_plans": [], "history": []}

def save_run_plans(data):
    """Save run plans to JSON file"""
    try:
        with open(RUN_PLAN_STORAGE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving run plans: {e}")
        raise

# Triage Genie jobs storage file
TRIAGE_GENIE_STORAGE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "triage_genie_jobs.json")

def load_triage_genie_jobs():
    """Load Triage Genie jobs from JSON file"""
    try:
        if os.path.exists(TRIAGE_GENIE_STORAGE):
            with open(TRIAGE_GENIE_STORAGE, 'r') as f:
                return json.load(f)
        return {"jobs": []}
    except Exception as e:
        logger.error(f"Error loading triage genie jobs: {e}")
        return {"jobs": []}

def save_triage_genie_jobs(data):
    """Save Triage Genie jobs to JSON file"""
    try:
        with open(TRIAGE_GENIE_STORAGE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving triage genie jobs: {e}")
        raise

# Regression Dashboard Configuration storage file
REGRESSION_CONFIG_STORAGE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "regression_config.json")

def load_regression_config():
    """Load regression dashboard configuration from JSON file. Migrates legacy schema."""
    try:
        if os.path.exists(REGRESSION_CONFIG_STORAGE):
            with open(REGRESSION_CONFIG_STORAGE, 'r') as f:
                config = json.load(f)
            # Migration: add default_tag, added_tags if missing
            added = config.get("added_tags", [])
            if not isinstance(added, list):
                added = []
            if "default_tag" not in config:
                existing_tag = config.get("tag", "").strip()
                if existing_tag:
                    config["default_tag"] = existing_tag
                    if existing_tag not in added:
                        added = list(added) + [existing_tag]
                else:
                    config["default_tag"] = None
            config["added_tags"] = added
            return config
        return {
            "input_mode": "tag",
            "tag": "cdp_master_full_reg",
            "default_tag": "cdp_master_full_reg",
            "added_tags": ["cdp_master_full_reg"],
            "task_ids": []
        }
    except Exception as e:
        logger.error(f"Error loading regression config: {e}")
        return {
            "input_mode": "tag",
            "tag": "cdp_master_full_reg",
            "default_tag": "cdp_master_full_reg",
            "added_tags": ["cdp_master_full_reg"],
            "task_ids": []
        }

def save_regression_config(data):
    """Save regression dashboard configuration to JSON file"""
    try:
        with open(REGRESSION_CONFIG_STORAGE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving regression config: {e}")
        raise

# Triage Accuracy Analyzer data storage
TRIAGE_ACCURACY_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TRIAGE_ACCURACY_TASKIDS_FILE = "triage_accuracy_data_taskids.json"

def _sanitize_tag_for_filename(tag):
    """Replace unsafe chars for filenames; collapse multiple underscores."""
    if not tag or not isinstance(tag, str):
        return "unknown"
    s = tag.strip()
    for c in r'|/:*?"<>\\':
        s = s.replace(c, "_")
    s = re.sub(r"_+", "_", s).strip("_")
    return s if s else "unknown"

def _triage_accuracy_path(tag=None):
    """Get path for triage accuracy JSON. tag=None means task_ids mode."""
    os.makedirs(TRIAGE_ACCURACY_DATA_DIR, exist_ok=True)
    if tag:
        sanitized = _sanitize_tag_for_filename(tag)
        return os.path.join(TRIAGE_ACCURACY_DATA_DIR, f"triage_accuracy_data_{sanitized}.json")
    return os.path.join(TRIAGE_ACCURACY_DATA_DIR, TRIAGE_ACCURACY_TASKIDS_FILE)

def load_triage_accuracy_data(tag=None):
    """Load triage accuracy data from JSON file. tag=None for task_ids mode."""
    try:
        path = _triage_accuracy_path(tag)
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        # Migration: copy legacy triage_accuracy_data.json to per-tag file if tag matches
        if tag:
            legacy_path = os.path.join(TRIAGE_ACCURACY_DATA_DIR, "triage_accuracy_data.json")
            if os.path.exists(legacy_path):
                with open(legacy_path, 'r') as f:
                    data = json.load(f)
                cached_tag = (data.get("tag") or "").strip()
                if cached_tag == tag:
                    save_triage_accuracy_data(data, tag)
                    return data
        return None
    except Exception as e:
        logger.error(f"Error loading triage accuracy data: {e}")
        return None

def save_triage_accuracy_data(data, tag=None):
    """Save triage accuracy data to JSON file. tag=None for task_ids mode."""
    try:
        path = _triage_accuracy_path(tag)
        os.makedirs(TRIAGE_ACCURACY_DATA_DIR, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving triage accuracy data: {e}")
        raise

def invalidate_triage_accuracy_cache(tag=None):
    """Delete triage accuracy cache. tag=None invalidates only task_ids file; pass tag for per-tag file."""
    try:
        path = _triage_accuracy_path(tag)
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Invalidated triage accuracy cache: {path}")
    except Exception as e:
        logger.warning(f"Could not invalidate triage accuracy cache: {e}")

# Load regression owners mapping from CSV
CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "regression_owners.csv")
owner_mapping = {}

def load_owner_mapping():
    """Load test prefix to owner mapping from CSV"""
    global owner_mapping
    try:
        if os.path.exists(CSV_PATH):
            df = pd.read_csv(CSV_PATH, header=0)
            # CSV format: "Test Area,Regression Owner"
            for _, row in df.iterrows():
                test_prefix = str(row.iloc[0]).strip()
                owner = str(row.iloc[1]).strip() if len(row) > 1 else "Unknown"
                if test_prefix and owner and test_prefix != "Test Area":  # Skip header row
                    owner_mapping[test_prefix] = owner
            logger.info(f"Loaded {len(owner_mapping)} owner mappings from CSV")
        else:
            logger.warning(f"CSV file not found at {CSV_PATH}")
    except Exception as e:
        logger.error(f"Error loading owner mapping: {e}")

# Load owner mapping on startup
load_owner_mapping()

# ======================================================
# Session (reused)
# ======================================================
session = requests.Session()
session.headers.update(HEADERS)
session.verify = False

# ======================================================
# Helpers
# ======================================================
def should_process_task(status):
    """Process only non-successful runs"""
    return status not in ("Succeeded", "Pending")


def fetch_test_result(testcase_id):
    resp = session.get(
        f"{PHX_BASE}/agave_test_results/{testcase_id}",
        timeout=30
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def process_failed_tests(task_id, agave_task):
    failed_tests = []

    agave_results = agave_task.get("AgaveTestResults", [])
    if not agave_results:
        return failed_tests

    failed_ids = [
        tr["$oid"]
        for tr in agave_results
        if tr.get("status") in ("Failed", "Warning")
    ][:MAX_FAILED_TESTS]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(fetch_test_result, tid)
            for tid in failed_ids
        ]

        for future in as_completed(futures):
            try:
                failure = future.result()
                failed_tests.append({
                    "testcase_id": failure.get("_id", {}).get("$oid"),
                    "test_name": failure.get("test", {}).get("name"),
                    "status": failure.get("status"),
                    "jira_tickets": failure.get("jira_tickets", []),
                    "exception_summary": failure.get("exception_summary"),
                    "log_url": failure.get("test_log_url")
                })
            except Exception as e:
                logger.error(f"[ERROR] Failed testcase fetch: {e}")

    return failed_tests


# ======================================================
# API-1: Fetch Regression Tasks
# ======================================================
def fetch_regression_tasks(tag=None, task_ids=None):
    """
    Fetch regression tasks either by tag or by task IDs
    
    Args:
        tag: Tag name to filter tasks
        task_ids: List of task IDs to fetch
    
    Returns:
        List of task data
    """
    if task_ids:
        # Fetch tasks by task IDs
        raw_query = {
            "_id": {
                "$in": [{"$oid": tid} for tid in task_ids]
            }
        }
    elif tag:
        # Fetch tasks by tag (original behavior)
        raw_query = {
            "$or": [
                {"created_by": "sudharshan.musali"},
                {"user_groups": {"$in": ["cdp_reg_jarvis"]}}
            ],
            "tester_tags": {"$in": [tag]},
            "system_under_test.component": "main"
        }
    else:
        raise ValueError("Either tag or task_ids must be provided")

    params = {
        "limit": 2000,
        "start": 0,
        "sort": "-_id",
        "only": (
            "label,branch,status,created_by,test_result_count,"
            "created_at,end_time"
        ),
        "raw_query": json.dumps(raw_query)
    }

    try:
        resp = session.get(
            f"{JITA_BASE}/tasks",
            params=params,
            timeout=30
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error fetching regression tasks: {e}")
        raise ConnectionError(f"Failed to connect to JITA API. Please check your network connection and ensure 'jita.eng.nutanix.com' is accessible.")
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error fetching regression tasks: {e}")
        raise TimeoutError(f"Request to JITA API timed out. Please try again.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching regression tasks: {e}")
        raise Exception(f"Error fetching regression tasks: {str(e)}")


# ======================================================
# API-2: Fetch Agave Task
# ======================================================
def fetch_agave_task(task_id):
    resp = session.get(
        f"{JITA_BASE}/agave_tasks/{task_id}",
        timeout=30
    )
    resp.raise_for_status()
    return resp.json().get("data", {})

# ======================================================
# Flask Endpoint
# ======================================================
def fetch_test_results_batch_with_pagination(task_ids, limit=2000, timeout=120):
    """
    Fetch test results for multiple tasks in batch.
    Always uses merge=True to get merged results across all tasks.
    Fetches all results in a single request with limit=2000.
    
    Args:
        task_ids: List of task IDs to fetch results for
        limit: Number of results to fetch (default: 2000)
        timeout: Request timeout in seconds (default: 120)
    
    Returns:
        List of merged test results
    
    Raises:
        requests.exceptions.Timeout: If request times out
        requests.exceptions.RequestException: For other request errors
    """
    if not task_ids:
        return []
    
    # Increase timeout for large task sets (more than 50 tasks)
    if len(task_ids) > 50:
        timeout = max(timeout, 180)  # At least 3 minutes for large sets
    
    logger.info(f"Fetching test results for {len(task_ids)} tasks (timeout: {timeout}s, limit: {limit})")
    
    # Correct payload structure for merged test results
    # Verified format: raw_query at top level with agave_task_id query, merge at top level
    payload = {
        "raw_query": {
            "agave_task_id": {
                "$in": [{"$oid": tid} for tid in task_ids]
            }
        },
        "only": (
            "_id,test,status,agave_task_id,jira_tickets,triaged_by,exception_summary,"
            "test_log_url,comments"
        ),
        "start": 0,
        "limit": limit,
        "sort": "agave_task_id,status",
        "merge": True  # Must be at top level to get merged results
    }
    
    # Log payload for verification
    #logger.info(f"[agave_test_results API] Payload: {json.dumps(payload, indent=2)}")
    #logger.info(f"[agave_test_results API] merge parameter: {payload.get('merge')}")
    logger.info(f"[agave_test_results API] Number of task_ids in query: {len(task_ids)}")
    
    try:
        resp = session.post(
            f"{JITA_BASE}/reports/agave_test_results",
            json=payload,
            timeout=timeout
        )
        
        resp.raise_for_status()
        response_data = resp.json()
        results = response_data.get("data", [])
        total = response_data.get("total", 0)
        
        # Log response info
        logger.info(f"[agave_test_results API] Response - Total: {total}, Returned: {len(results)}, Merge enabled: {payload.get('merge')}")
        if results:
            # Log sample test names to verify merge (first 3 unique test names)
            sample_tests = []
            seen_sample = set()
            for r in results:
                test_name = r.get("test", {}).get("name", "")
                if test_name and test_name not in seen_sample and len(sample_tests) < 3:
                    sample_tests.append(test_name)
                    seen_sample.add(test_name)
            logger.info(f"[agave_test_results API] Sample test names (first 3 unique): {sample_tests}")
        
        logger.info(f"Fetched {len(results)} merged test results from {len(task_ids)} tasks")
        return results
        
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout fetching test results: {e}")
        raise requests.exceptions.Timeout(
            f"Request timed out after {timeout}s while fetching test results. "
            f"This may be due to a large number of tasks ({len(task_ids)}). "
            f"Try reducing the number of tasks or increasing the timeout."
        ) from e
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching test results: {e}")
        raise

@app.route("/mcp/regression/home", methods=["GET"])
def regression_home():
    start = time.time()

    tag = request.args.get("tag")
    task_ids_param = request.args.get("task_ids")  # Comma-separated task IDs
    
    # Parse task_ids if provided
    task_ids = None
    if task_ids_param:
        task_ids = [tid.strip() for tid in task_ids_param.split(",") if tid.strip()]
    
    if not tag and not task_ids:
        return jsonify({"error": "Either tag or task_ids is required"}), 400

    if tag:
        logger.info(f"[START] Regression Home | tag={tag}")
    else:
        logger.info(f"[START] Regression Home | task_ids={len(task_ids)} tasks")
        logger.info(f"[DEBUG] Requested task IDs: {task_ids[:5]}..." if len(task_ids) > 5 else f"[DEBUG] Requested task IDs: {task_ids}")

    # Store original requested task IDs for comparison
    requested_task_ids = task_ids.copy() if task_ids else None
    
    tasks = fetch_regression_tasks(tag=tag, task_ids=task_ids)
    
    # Log which task IDs were found vs requested
    if requested_task_ids and not tag:
        found_task_ids = [task["_id"]["$oid"] for task in tasks]
        missing_task_ids = set(requested_task_ids) - set(found_task_ids)
        logger.info(f"[DEBUG] Found {len(found_task_ids)}/{len(requested_task_ids)} tasks")
        if missing_task_ids:
            logger.warning(f"[DEBUG] Missing task IDs ({len(missing_task_ids)}): {list(missing_task_ids)[:5]}..." if len(missing_task_ids) > 5 else f"[DEBUG] Missing task IDs: {list(missing_task_ids)}")
        
        # Log branch distribution from raw JITA data
        if tasks:
            branch_distribution = {}
            for task in tasks:
                raw_branch = task.get("branch", "None")
                branch_distribution[raw_branch] = branch_distribution.get(raw_branch, 0) + 1
            logger.info(f"[DEBUG] Raw branch distribution from JITA: {branch_distribution}")
    
    # Collect all task IDs from found tasks
    task_ids = [task["_id"]["$oid"] for task in tasks]
    
    # Fetch test results using agave_test_results API for accurate counts
    logger.info(f"Fetching test results for {len(task_ids)} tasks using agave_test_results API")
    test_results = []
    if task_ids:
        try:
            test_results = fetch_test_results_batch_with_pagination(task_ids)
            logger.info(f"Fetched {len(test_results)} test results")
        except Exception as e:
            logger.warning(f"Failed to fetch test results from agave_test_results API: {e}. Falling back to test_result_count.")
            test_results = []
    
    # Group test results by task_id
    test_results_by_task = defaultdict(list)
    for test_result in test_results:
        agave_task_id = test_result.get("agave_task_id")
        if agave_task_id:
            # Handle both string and $oid format
            if isinstance(agave_task_id, dict) and "$oid" in agave_task_id:
                task_id = agave_task_id["$oid"]
            else:
                task_id = str(agave_task_id)
            test_results_by_task[task_id].append(test_result)
    
    runs = []
    
    # Track created_at times for finding oldest start date
    created_at_times = []

    for task in tasks:
        task_id = task["_id"]["$oid"]
        status = task.get("status")
        
        # Collect created_at time for oldest date calculation
        created_at = task.get("created_at")
        if created_at:
            created_at_times.append(created_at)
        
        # Count test statuses from agave_test_results if available
        test_counts = {
            "total": 0,
            "Succeeded": 0,
            "Failed": 0,
            "Pending": 0,
            "Warning": 0,
            "Running": 0,
            "Skipped": 0,
            "Killed": 0
        }
        
        if task_id in test_results_by_task:
            # Count statuses from actual test results
            for test_result in test_results_by_task[task_id]:
                test_status = test_result.get("status", "")
                test_counts["total"] += 1
                
                # Normalize status names (handle case-insensitive matching)
                status_lower = test_status.lower() if test_status else ""
                
                if status_lower == "succeeded" or status_lower == "success":
                    test_counts["Succeeded"] += 1
                elif status_lower == "failed" or status_lower == "failure":
                    test_counts["Failed"] += 1
                elif status_lower == "pending" or status_lower == "waiting":
                    test_counts["Pending"] += 1
                elif status_lower == "warning" or status_lower == "warn":
                    test_counts["Warning"] += 1
                elif status_lower == "running" or status_lower == "executing" or status_lower == "in_progress":
                    test_counts["Running"] += 1
                elif status_lower == "skipped" or status_lower == "skip":
                    test_counts["Skipped"] += 1
                elif status_lower == "killed" or status_lower == "terminated" or status_lower == "cancelled":
                    test_counts["Killed"] += 1
                else:
                    # For unknown statuses, try to infer from common patterns
                    # But don't default to pending - log it for debugging
                    logger.debug(f"Unknown test status: {test_status} for task {task_id}")
                    # Map unknown statuses based on common patterns
                    if any(x in status_lower for x in ["pending", "waiting", "queued"]):
                        test_counts["Pending"] += 1
                    elif any(x in status_lower for x in ["running", "executing", "in_progress", "active"]):
                        test_counts["Running"] += 1
                    elif any(x in status_lower for x in ["skipped", "skip"]):
                        test_counts["Skipped"] += 1
                    elif any(x in status_lower for x in ["killed", "terminated", "cancelled", "aborted"]):
                        test_counts["Killed"] += 1
                    else:
                        # Default to pending only if truly unknown
                        test_counts["Pending"] += 1
        else:
            # Fallback to test_result_count if agave_test_results not available
            tc = task.get("test_result_count", {})
            test_counts = {
                "total": tc.get("Total", 0),
                "Succeeded": tc.get("Succeeded", 0),
                "Failed": tc.get("Failed", 0),
                "Pending": tc.get("Pending", 0),
                "Warning": tc.get("Warning", 0),
                "Running": tc.get("Running", 0),
                "Skipped": tc.get("Skipped", 0),
                "Killed": tc.get("Killed", 0)
            }

        # Get branch and normalize it
        original_branch = task.get("branch")
        label = task.get("label", "")
        branch = None
        
        if original_branch:
            # Branch exists, normalize it
            branch = original_branch.strip()
            # Normalize master branch variations (case-insensitive)
            branch_lower = branch.lower()
            if branch_lower in ["master", "main"]:
                branch = "master"
            elif branch_lower in ["ganges-7.5-stable", "ganges_7.5_stable"]:
                branch = "ganges-7.5-stable"
        else:
            # Branch is missing (None, empty string, etc.)
            # Try to infer from label
            label_lower = label.lower()
            
            # Check for master branch indicators in label
            master_keywords = ["master", "main", "cdp_master", "master_full", "master_reg"]
            if any(keyword in label_lower for keyword in master_keywords):
                branch = "master"
                logger.info(f"[BRANCH_INFER] Task {task_id}: No branch field, inferred 'master' from label: '{label}'")
            # Check for other known branch patterns
            elif "ganges" in label_lower or "7.5" in label_lower:
                branch = "ganges-7.5-stable"
                logger.info(f"[BRANCH_INFER] Task {task_id}: No branch field, inferred 'ganges-7.5-stable' from label: '{label}'")
            else:
                branch = "unknown"
                logger.warning(f"[BRANCH_MISSING] Task {task_id}: No branch field and cannot infer from label: '{label}'")
        
        # Log master branch detection for debugging
        if branch == "master":
            logger.info(f"[MASTER_BRANCH] Task {task_id}: branch='{original_branch}' -> normalized to 'master', label='{label}'")
        
        # Get created_at time for this task
        created_at = task.get("created_at")
        
        run = {
            "task_id": task_id,
            "label": label,
            "branch": branch,
            "status": status,
            "created_by": task.get("created_by"),
            "created_at": created_at,  # Include created_at in run object
            "test_counts": test_counts,
            "failed_tests": []
        }

        if not should_process_task(status):
            agave_task = fetch_agave_task(task_id)
            run["failed_tests"] = process_failed_tests(task_id, agave_task)

        runs.append(run)

    # Calculate oldest start date per branch from all runs
    branch_start_dates = {}  # {branch: oldest_datetime}
    
    for run in runs:
        branch = run.get("branch")
        created_at = run.get("created_at")
        
        if branch and created_at:
            try:
                # Parse created_at time
                if isinstance(created_at, str):
                    # Handle ISO format
                    if 'T' in created_at:
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    else:
                        # Try other common formats
                        try:
                            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            dt = datetime.strptime(created_at, "%Y-%m-%d")
                elif isinstance(created_at, dict) and "$date" in created_at:
                    # MongoDB date format
                    dt = datetime.fromtimestamp(created_at["$date"] / 1000)
                else:
                    continue
                
                # Track oldest date per branch
                if branch not in branch_start_dates or dt < branch_start_dates[branch]:
                    branch_start_dates[branch] = dt
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not parse created_at for branch {branch}: {created_at}, error: {e}")
                continue
    
    # Format branch start dates as readable strings
    branch_start_dates_formatted = {}
    for branch, dt in branch_start_dates.items():
        branch_start_dates_formatted[branch] = dt.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[DEBUG] Oldest start date for branch '{branch}': {branch_start_dates_formatted[branch]}")
    
    # Calculate overall oldest start date
    oldest_start_date = None
    if branch_start_dates:
        oldest_start_date = min(branch_start_dates.values())
        oldest_start_date_str = oldest_start_date.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[DEBUG] Overall oldest start date: {oldest_start_date_str}")

    # Log final branch distribution after normalization
    if runs:
        final_branch_dist = {}
        for run in runs:
            br = run.get("branch", "None")
            final_branch_dist[br] = final_branch_dist.get(br, 0) + 1
        logger.info(f"[DEBUG] Final branch distribution after normalization: {final_branch_dist}")
        if "master" in final_branch_dist:
            logger.info(f"[DEBUG] Master branch tasks found: {final_branch_dist['master']} tasks")
        else:
            logger.warning(f"[DEBUG] No 'master' branch found in final distribution! Available branches: {list(final_branch_dist.keys())}")

    logger.info(
        f"[END] runs={len(runs)} | time={time.time() - start:.2f}s"
    )
    
    # Include metadata about missing task IDs if using task_ids mode
    response_data = {
        "tag": tag,
        "generated_at": datetime.utcnow().isoformat(),
        "total_runs": len(runs),
        "runs": runs,
        "branch_start_dates": branch_start_dates_formatted,  # Oldest start date per branch
        "oldest_start_date": oldest_start_date.strftime("%Y-%m-%d %H:%M:%S") if oldest_start_date else None
    }
    
    if requested_task_ids and not tag:
        found_task_ids = [task["_id"]["$oid"] for task in tasks]
        missing_task_ids = list(set(requested_task_ids) - set(found_task_ids))
        if missing_task_ids:
            response_data["missing_task_ids"] = missing_task_ids
            response_data["requested_count"] = len(requested_task_ids)
            response_data["found_count"] = len(found_task_ids)
            logger.warning(f"Some task IDs were not found: {len(missing_task_ids)} missing out of {len(requested_task_ids)} requested")

    return jsonify(response_data)


# ---------------------------------------------------
# Manual Tasks Endpoints
# ---------------------------------------------------
@app.route("/mcp/regression/manual-tasks", methods=["GET"])
def get_manual_tasks():
    tag = request.args.get("tag")
    branch = request.args.get("branch")

    if not tag:
        return jsonify({"error": "tag is required"}), 400

    if not branch:
        return jsonify({"error": "branch is required"}), 400

    # Get manual tasks for the given tag and branch
    tag_store = manual_tasks_store.get(tag, {})
    task_ids = tag_store.get(branch, [])

    return jsonify({
        "tag": tag,
        "branch": branch,
        "manual_tasks": task_ids
    })


@app.route("/mcp/regression/manual-tasks", methods=["POST"])
def add_manual_tasks():
    data = request.get_json()
    tag = data.get("tag")
    branch = data.get("branch")
    task_ids = data.get("task_ids", [])

    if not tag:
        return jsonify({"error": "tag is required"}), 400

    if not branch:
        return jsonify({"error": "branch is required"}), 400

    if not task_ids:
        return jsonify({"error": "task_ids is required"}), 400

    # Initialize storage if needed
    if tag not in manual_tasks_store:
        manual_tasks_store[tag] = {}

    if branch not in manual_tasks_store[tag]:
        manual_tasks_store[tag][branch] = []

    # Add new task IDs (avoid duplicates)
    existing = set(manual_tasks_store[tag][branch])
    for task_id in task_ids:
        if task_id not in existing:
            manual_tasks_store[tag][branch].append(task_id)

    return jsonify({
        "tag": tag,
        "branch": branch,
        "manual_tasks": manual_tasks_store[tag][branch]
    })


@app.route("/mcp/regression/manual-tasks", methods=["DELETE"])
def remove_manual_task():
    tag = request.args.get("tag")
    branch = request.args.get("branch")
    task_id = request.args.get("task_id")

    if not tag:
        return jsonify({"error": "tag is required"}), 400

    if not branch:
        return jsonify({"error": "branch is required"}), 400

    if not task_id:
        return jsonify({"error": "task_id is required"}), 400

    # Remove task ID if it exists
    if tag in manual_tasks_store and branch in manual_tasks_store[tag]:
        if task_id in manual_tasks_store[tag][branch]:
            manual_tasks_store[tag][branch].remove(task_id)

    return jsonify({
        "tag": tag,
        "branch": branch,
        "manual_tasks": manual_tasks_store.get(tag, {}).get(branch, [])
    })


# ---------------------------------------------------
# Configuration Endpoints
# ---------------------------------------------------
@app.route("/mcp/regression/config", methods=["GET"])
def get_regression_config():
    """Get regression dashboard configuration from JSON file"""
    try:
        config = load_regression_config()
        return jsonify(config)
    except Exception as e:
        logger.error(f"Error getting regression config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/mcp/regression/config", methods=["POST"])
def save_regression_config_endpoint():
    """Save regression dashboard configuration to JSON file"""
    try:
        data = request.get_json()
        
        # Validate required fields
        input_mode = data.get("input_mode")
        if input_mode not in ["tag", "task_ids"]:
            return jsonify({"error": "input_mode must be 'tag' or 'task_ids'"}), 400
        
        default_tag = data.get("default_tag")
        added_tags = data.get("added_tags")
        if added_tags is None:
            added_tags = []
        if not isinstance(added_tags, list):
            added_tags = []
        
        config = {
            "input_mode": input_mode,
            "default_tag": default_tag if default_tag else None,
            "added_tags": [str(t).strip() for t in added_tags if t and str(t).strip()],
            "tag": (default_tag or "").strip() if input_mode == "tag" else "",
            "task_ids": data.get("task_ids", []) if input_mode == "task_ids" else []
        }
        
        # Validate based on input mode
        if input_mode == "tag":
            if config["default_tag"] and config["default_tag"] not in config["added_tags"]:
                return jsonify({"error": "default_tag must be in added_tags or null"}), 400
            config["task_ids"] = []
        elif input_mode == "task_ids":
            if not config["task_ids"] or len(config["task_ids"]) == 0:
                return jsonify({"error": "task_ids is required when input_mode is 'task_ids'"}), 400
            config["tag"] = ""
            config["default_tag"] = None
        
        save_regression_config(config)
        if input_mode == "task_ids":
            invalidate_triage_accuracy_cache(None)
        logger.info(f"Saved regression config: input_mode={input_mode}, default_tag={config.get('default_tag')}, added_tags={len(config.get('added_tags', []))}")
        return jsonify(config)
    except Exception as e:
        logger.error(f"Error saving regression config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/mcp/regression/config/tags", methods=["POST"])
def add_config_tag():
    """Add a tag to added_tags. Validation is lenient - tag is added even if JITA returns empty."""
    try:
        data = request.get_json() or {}
        tag = (data.get("tag") or "").strip()
        if not tag:
            return jsonify({"error": "tag is required"}), 400
        
        config = load_regression_config()
        added = list(config.get("added_tags", []))
        if tag in added:
            return jsonify({"added_tags": added, "message": "Tag already in list"}), 200
        
        # Optional validation: if JITA returns tasks, tag is validated; otherwise still add (lenient)
        validated = False
        try:
            tasks = fetch_regression_tasks(tag=tag)
            validated = bool(tasks)
        except Exception as e:
            logger.warning(f"Tag validation skipped for '{tag}': {e}")
        
        added.append(tag)
        config["added_tags"] = added
        save_regression_config(config)
        logger.info(f"Added tag to config: {tag} (validated={validated})")
        return jsonify({"added_tags": added, "tag": tag, "validated": validated})
    except Exception as e:
        logger.error(f"Error adding tag: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/mcp/regression/config/tags", methods=["DELETE"])
def delete_config_tag():
    """Remove tag from added_tags and delete per-tag triage accuracy JSON."""
    try:
        tag = request.args.get("tag", "").strip()
        if not tag:
            return jsonify({"error": "tag query param is required"}), 400
        
        config = load_regression_config()
        added = list(config.get("added_tags", []))
        if tag not in added:
            return jsonify({"error": f"Tag '{tag}' not in added_tags"}), 404
        
        added = [t for t in added if t != tag]
        config["added_tags"] = added
        if config.get("default_tag") == tag:
            config["default_tag"] = None
            config["tag"] = ""
        save_regression_config(config)
        
        invalidate_triage_accuracy_cache(tag)
        logger.info(f"Deleted tag from config and triage JSON: {tag}")
        return jsonify({"added_tags": added})
    except Exception as e:
        logger.error(f"Error deleting tag: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------
# Fetch Branches from Tag Endpoint
# ---------------------------------------------------
@app.route("/mcp/regression/branches", methods=["GET"])
def get_branches_from_tag():
    tag = request.args.get("tag")
    
    if not tag:
        return jsonify({"error": "tag is required"}), 400
    
    try:
        # Fetch tasks using the same API as regression_home
        tasks = fetch_regression_tasks(tag)
        
        # Extract unique branches
        branches = set()
        for task in tasks:
            branch = task.get("branch")
            if branch:
                branches.add(branch)
        
        return jsonify({
            "tag": tag,
            "branches": sorted(list(branches))
        })
    except Exception as e:
        logger.error(f"Error fetching branches: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------
# Helper: Resolve Owner from Test Name
# ---------------------------------------------------
def resolve_owner(test_name):
    """Resolve owner from test name using prefix mapping"""
    for prefix, owner in owner_mapping.items():
        if test_name.startswith(prefix):
            return owner
    return "Unknown"


# ---------------------------------------------------
# Helper: Fetch Test Results (POST API – batch)
# NOTE: This function is deprecated. Use fetch_test_results_batch_with_pagination() instead.
# Kept for backward compatibility but redirects to pagination version.
# ---------------------------------------------------
def fetch_test_results_batch(task_ids):
    """Fetch test results for multiple tasks in batch (deprecated - uses pagination version)"""
    return fetch_test_results_batch_with_pagination(task_ids)


# ---------------------------------------------------
# Helper function to calculate QI impact for bulk issues
# ---------------------------------------------------
def calculate_bulk_issues_qi_impact(bulk_issues, test_data, tag=None):
    """
    Calculate QI impact for bulk issues using TCMS API.
    
    Args:
        bulk_issues: Dictionary mapping ticket -> list of testcase names
        test_data: List of test result data from API
        tag: Optional tag to extract milestone from
    
    Returns:
        Dictionary with:
        - bulk_issues_with_qi: Dict mapping ticket -> QI impact data
        - test_qi_map: Dict mapping testcase_name -> QI value
    """
    if not bulk_issues:
        return {"bulk_issues_with_qi": {}, "test_qi_map": {}}
    
    # Extract milestone from tag or use default
    milestone = "7.5.1"  # Default milestone
    if tag:
        # Try to extract milestone from tag (e.g., "cdp_master_full_reg" -> "master", "7.5.1" -> "7.5.1")
        milestone_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', tag)
        if milestone_match:
            milestone = milestone_match.group(1)
        elif "master" in tag.lower():
            milestone = "master"
    
    # Collect all unique testcases from bulk issues for TCMS API calls
    all_bulk_testcases = set()
    for test_names in bulk_issues.values():
        all_bulk_testcases.update(test_names)
    
    # Fetch QI values from TCMS API for all testcases in bulk issues
    logger.info(f"Fetching QI from TCMS API for {len(all_bulk_testcases)} testcases in bulk issues (milestone: {milestone})")
    test_qi_map = {}
    
    # Use ThreadPoolExecutor to fetch QI values in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_testcase = {
            executor.submit(fetch_qi_from_tcms, testcase_name, milestone): testcase_name
            for testcase_name in all_bulk_testcases
        }
        
        for future in as_completed(future_to_testcase):
            testcase_name = future_to_testcase[future]
            try:
                qi_value = future.result()
                if qi_value is not None:
                    test_qi_map[testcase_name] = qi_value
                else:
                    # Fallback: use status-based QI if TCMS API doesn't return data
                    # Find the test in test_data to get status
                    status_qi = 0
                    for test in test_data:
                        if test.get("test", {}).get("name") == testcase_name:
                            status = test.get("status", "")
                            if status == "Succeeded":
                                status_qi = 100
                            elif status == "Warning":
                                status_qi = 50
                            else:
                                status_qi = 0
                            break
                    test_qi_map[testcase_name] = status_qi
            except Exception as e:
                logger.warning(f"Error fetching QI for {testcase_name}: {e}")
                # Fallback to 0 if error
                test_qi_map[testcase_name] = 0
    
    logger.info(f"Fetched QI values for {len(test_qi_map)} testcases from TCMS API")
    
    # Calculate QI impact for each bulk issue using generate_qi_impact logic
    bulk_issues_with_qi = {}
    # Use total unique test cases from all test data (not just failed)
    all_unique_tests = set()
    for test in test_data:
        test_name = test.get("test", {}).get("name", "")
        if test_name:
            all_unique_tests.add(test_name)
    total_test_cases = len(all_unique_tests) if all_unique_tests else 1  # Avoid division by zero
    
    for ticket, test_names in bulk_issues.items():
        # Get QI values for all testcases affected by this ticket
        qi_values = []
        testcase_qi_details = []  # Store individual testcase QI details
        for test_name in test_names:
            qi_value = test_qi_map.get(test_name, 0)
            qi_values.append(qi_value)
            testcase_qi_details.append({
                "testcase": test_name,
                "qi": qi_value
            })
        
        if qi_values:
            # Calculate average QI (matching generate_qi_impact logic)
            average_qi = sum(qi_values) / len(qi_values)
            nr_test_cases = len(test_names)
            
            # Calculate QI impact: (average_qi - 100) * nr_test_cases
            qi_impact = (average_qi - 100) * nr_test_cases
            
            # Calculate overall QI impact: 100 * (qi_impact / (100 * total_test_cases))
            if total_test_cases > 0:
                overall_qi_impact = 100 * (qi_impact / (100 * total_test_cases))
            else:
                overall_qi_impact = 0
            
            bulk_issues_with_qi[ticket] = {
                "testcases": test_names,
                "testcase_count": nr_test_cases,
                "average_qi": round(average_qi, 2),
                "qi_impact": round(qi_impact, 2),
                "overall_qi_impact": round(overall_qi_impact, 2),
                "testcase_qi_details": testcase_qi_details  # Include individual testcase QI details
            }
        else:
            # Fallback if no QI data
            bulk_issues_with_qi[ticket] = {
                "testcases": test_names,
                "testcase_count": len(test_names),
                "average_qi": 0,
                "qi_impact": 0,
                "overall_qi_impact": 0,
                "testcase_qi_details": []
            }
    
    return {
        "bulk_issues_with_qi": bulk_issues_with_qi,
        "test_qi_map": test_qi_map
    }


# ---------------------------------------------------
# Helper function to fetch QI from TCMS API
# ---------------------------------------------------
def fetch_qi_from_tcms(testcase_name, milestone="7.5.1"):
    """
    Fetch QI (operation_success_percentage) from TCMS API for a given testcase.
    
    Args:
        testcase_name: Name of the testcase (e.g., "cdp.counter.fio.test_fio_counters.CountersFIOTest.test_fio_end_to_end")
        milestone: Target milestone (default: "7.5.1")
    
    Returns:
        float: QI value (operation_success_percentage) or None if not found/error
    """
    try:
        # Construct payload based on the provided example
        # Use more flexible matching - try exact name match first, then regex
        payload = [{
            "$match": {
                "$and": [
                    {"target_milestone": milestone},
                    {"last_result": {"$elemMatch": {"pass_name": "overall"}}},
                    {"deleted": False},
                    {"test_case.metadata.tags": {"$nin": ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]}},
                    {
                        "$or": [
                            {"test_case.name": testcase_name},  # Exact match first
                            {"test_case.name": {"$regex": testcase_name, "$options": "i"}}  # Case-insensitive regex
                        ]
                    },
                    {"test_case.deprecated": False}
                ]
            }
        }, {"$sort": {"name": 1}}, {"$skip": 0}, {"$limit": 50}]
        
        # Make POST request to TCMS API
        response = requests.post(
            f"{TCMS_BASE}/milestone_all_test_cases/aggregate",
            json=payload,
            headers={"Content-Type": "application/json"},
            verify=False,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("data") and len(data["data"]) > 0:
                # Extract operation_success_percentage from published section
                testcase_data = data["data"][0]
                last_result = testcase_data.get("last_result", [])
                if last_result and len(last_result) > 0:
                    published = last_result[0].get("published", {})
                    if published:
                        operation_success_percentage = published.get("operation_success_percentage")
                        if operation_success_percentage is not None:
                            return float(operation_success_percentage)
            
            logger.warning(f"TCMS API: No QI data found for testcase: {testcase_name}")
            return None
        else:
            logger.warning(f"TCMS API error for {testcase_name}: HTTP {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        logger.warning(f"TCMS API timeout for testcase: {testcase_name}")
        return None
    except Exception as e:
        logger.warning(f"Error fetching QI from TCMS for {testcase_name}: {e}")
        return None


# ---------------------------------------------------
# Triage Count Endpoint
# ---------------------------------------------------
@app.route("/mcp/regression/triage-count", methods=["GET"])
def get_triage_count():
    start = time.time()
    tag = request.args.get("tag")
    task_ids_param = request.args.get("task_ids")  # Comma-separated task IDs
    
    # Parse task_ids if provided
    task_ids = None
    if task_ids_param:
        task_ids = [tid.strip() for tid in task_ids_param.split(",") if tid.strip()]
    
    if not tag and not task_ids:
        return jsonify({"error": "Either tag or task_ids is required"}), 400
    
    if tag:
        logger.info(f"[START] Triage Count | tag={tag}")
    else:
        logger.info(f"[START] Triage Count | task_ids={len(task_ids)} tasks")
    
    try:
        # Reload owner mapping in case it was updated
        load_owner_mapping()
        
        # Fetch tasks for the tag or task IDs
        tasks = fetch_regression_tasks(tag=tag, task_ids=task_ids)
        logger.info(f"Tasks count: {len(tasks)}")
        
        if not tasks:
            return jsonify({
                "tag": tag,
                "generated_at": datetime.utcnow().isoformat(),
                "triage_summary": {},
                "owner_ticket_map": {},
                "bulk_issues": {},
                "pending_tests": 0,
                "message": "No tasks found for this tag"
            })
        
        # Collect all task IDs
        task_ids = []
        for task in tasks:
            task_id = task["_id"]["$oid"]
            task_ids.append(task_id)
        
        # Validate tasks exist and fetch test results in batch
        logger.info(f"Fetching test results for {len(task_ids)} tasks")
        try:
            # Use longer timeout for triage count as it may process many tasks
            test_data = fetch_test_results_batch_with_pagination(task_ids, timeout=180)
            logger.info(f"Fetched {len(test_data)} merged test results")
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout error in triage count: {e}")
            return jsonify({
                "error": f"Request timed out while fetching test results. This may be due to a large number of tasks ({len(task_ids)}). Please try with fewer tasks or contact support.",
                "type": "timeout_error",
                "task_count": len(task_ids)
            }), 504
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error in triage count: {e}")
            return jsonify({
                "error": f"Failed to fetch test results: {str(e)}",
                "type": "request_error"
            }), 500
        
        # Initialize data structures
        summary = defaultdict(lambda: {
            "Total Failed": 0,
            "Triaged": 0,
            "UnTriaged": 0,
            "Bulk Issues": 0
        })
        ticket_case_map = defaultdict(set)  # ticket → set of unique testcases
        owner_ticket_map = defaultdict(lambda: defaultdict(int))  # owner → ticket → count
        inprogress_tests = 0  # Count pending/running from merged test results
        
        # Deduplicate by test name to ensure each unique test is counted only once
        # This handles cases where merge might not fully deduplicate or same test appears with different statuses
        seen_tests = set()  # Track unique test names we've processed
        seen_pending_running = set()  # Track unique test names for pending/running
        
        # Process test data - matching the working script logic
        for test in test_data:
            status = test.get("status")
            test_name = test.get("test", {}).get("name", "")
            
            # Skip if test name is empty
            if not test_name:
                continue
            
            # Skip succeeded tests
            if status == "Succeeded":
                continue
            
            # Count pending/running tests as in-progress (from merged results)
            # Deduplicate by test name to avoid double counting
            if status == "Pending":
                if test_name not in seen_pending_running:
                    inprogress_tests += 1
                    seen_pending_running.add(test_name)
                continue
            if status == "Running":
                if test_name not in seen_pending_running:
                    inprogress_tests += 1
                    seen_pending_running.add(test_name)
                continue
            
            # Process failed tests only (excluding Succeeded, Pending, Running)
            # Deduplicate by test name to ensure each unique test is counted only once
            if test_name in seen_tests:
                continue  # Skip if we've already processed this test
            
            seen_tests.add(test_name)
            tickets = test.get("jira_tickets", [])
            owner = resolve_owner(test_name)
            
            # Summary stats
            summary[owner]["Total Failed"] += 1
            if tickets:
                summary[owner]["Triaged"] += 1
            else:
                summary[owner]["UnTriaged"] += 1
            
            # Update ticket-to-test map (using set to avoid duplicates)
            for ticket in tickets:
                ticket_case_map[ticket].add(test_name)
                owner_ticket_map[owner][ticket] += 1
        
        # Identify bulk issues (tickets with >5 testcases)
        # Convert sets to lists for JSON serialization
        bulk_issues = {ticket: list(tests) for ticket, tests in ticket_case_map.items() if len(tests) > 5}
        
        # Calculate QI impact for bulk issues only if requested (to speed up triage count)
        include_bulk_qi = request.args.get("include_bulk_qi", "false").lower() == "true"
        bulk_issues_with_qi = {}
        if include_bulk_qi and bulk_issues:
            logger.info("Calculating QI impact for bulk issues (this may take longer)...")
            qi_calculation_result = calculate_bulk_issues_qi_impact(bulk_issues, test_data, tag)
            bulk_issues_with_qi = qi_calculation_result["bulk_issues_with_qi"]
        else:
            logger.info("Skipping bulk issues QI calculation for faster triage count response")
        
        # Update bulk issues count per owner
        for owner in summary:
            owner_tickets = owner_ticket_map[owner]
            bulk_ticket_count = sum(1 for ticket in owner_tickets if ticket in bulk_issues)
            summary[owner]["Bulk Issues"] = bulk_ticket_count
        
        # Convert defaultdict to regular dict for JSON serialization
        triage_summary = {k: dict(v) for k, v in summary.items()}
        owner_ticket_dict = {k: dict(v) for k, v in owner_ticket_map.items()}
        bulk_issues_dict = {k: v for k, v in bulk_issues.items()}
        
        logger.info(f"[END] Triage Count | time={time.time() - start:.2f}s")
        logger.info(f"Triage Summary: {triage_summary}")
        logger.info(f"Owner Ticket Map: {owner_ticket_dict}")
        logger.info(f"Bulk Issues: {bulk_issues_dict}")
        logger.info(f"Bulk Issues with QI: {bulk_issues_with_qi}")
        logger.info(f"Pending Tests: {inprogress_tests}")
        logger.info(f"Total Tests Processed: {len(test_data)}")
        
        return jsonify({
            "tag": tag or None,
            "task_ids": task_ids if task_ids else None,
            "generated_at": datetime.utcnow().isoformat(),
            "triage_summary": triage_summary,
            "owner_ticket_map": owner_ticket_dict,
            "bulk_issues": bulk_issues_dict,
            "bulk_issues_with_qi": bulk_issues_with_qi,
            "pending_tests": inprogress_tests,
            "total_tests_processed": len(test_data)
        })
    except Exception as e:
        logger.error(f"Error in triage count: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------
# Triage Accuracy Analyzer Endpoint
# ---------------------------------------------------
def _config_matches_cached(cached, tag, task_ids):
    """Check if cached data matches current tag/task_ids config."""
    if not cached:
        return False
    cached_tag = (cached.get("tag") or "").strip()
    cached_task_ids = cached.get("task_ids") or []
    req_tag = (tag or "").strip()
    req_task_ids = sorted([str(t).strip() for t in (task_ids or []) if t and str(t).strip()])
    cached_task_ids_sorted = sorted([str(t).strip() for t in cached_task_ids if t])
    # Tag mode: match by tag only
    if req_tag:
        return req_tag == cached_tag
    # Task IDs mode: match by task_ids
    return req_task_ids == cached_task_ids_sorted


@app.route("/mcp/regression/triage-accuracy", methods=["GET"])
@app.route("/api/mcp/regression/triage-accuracy", methods=["GET"])
def get_triage_accuracy():
    """Triage Accuracy Analyzer: fetch Failed+Warning testcases, compare Jira vs Triage Genie, store in JSON."""
    start = time.time()
    tag = request.args.get("tag")
    if tag is not None:
        tag = (tag or "").strip() or None
    task_ids_param = request.args.get("task_ids")
    task_ids = None
    if task_ids_param:
        task_ids = [tid.strip() for tid in task_ids_param.split(",") if tid.strip()]

    # Fall back to config if params missing
    if not tag and not task_ids:
        config = load_regression_config()
        if config.get("input_mode") == "tag":
            tag = config.get("default_tag") or config.get("tag", "") or ""
        if not tag and config.get("input_mode") == "task_ids" and config.get("task_ids"):
            task_ids = config.get("task_ids", [])

    if not tag and not task_ids:
        return jsonify({"error": "Either tag or task_ids is required"}), 400

    if tag:
        logger.info(f"[START] Triage Accuracy | tag={tag}")
    else:
        logger.info(f"[START] Triage Accuracy | task_ids={len(task_ids)} tasks")

    try:
        load_owner_mapping()
        cache_tag = tag if tag else None
        reload = request.args.get("reload", "false").lower() == "true"
        if reload:
            invalidate_triage_accuracy_cache(cache_tag)
            cached = None
            logger.info("[Triage Accuracy] Cache invalidated, fetching fresh data")
        else:
            cached = load_triage_accuracy_data(cache_tag)
        if cached and _config_matches_cached(cached, tag, task_ids):
            logger.info("[Triage Accuracy] Using cached data")
            return jsonify(cached)

        tasks = fetch_regression_tasks(tag=tag, task_ids=task_ids)
        if not tasks:
            result = {
                "generated_time": datetime.utcnow().isoformat(),
                "tag": tag or None,
                "task_ids": list(task_ids) if task_ids else [],
                "testcases": [],
                "triage_summary": {
                    "total_failed_warning_count": 0,
                    "triaged_count": 0,
                    "triage_genie_count": 0,
                    "total_triage_genie_count": 0,
                    "triage_completed_percent": 0,
                    "triage_genie_percent": 0,
                    "total_triage_genie_percent": 0,
                    "matched_count": 0,
                    "unmatched_count": 0,
                    "matched_percent": 0,
                    "unmatched_percent": 0,
                },
            }
            save_triage_accuracy_data(result, cache_tag)
            return jsonify(result)

        collected_task_ids = [t["_id"]["$oid"] for t in tasks]
        logger.info(f"Fetching test results for {len(collected_task_ids)} tasks")
        test_data = fetch_test_results_batch_with_pagination(collected_task_ids, timeout=180)

        # Filter Failed or Warning; deduplicate by test name
        failed_warning = [
            tr for tr in test_data
            if tr.get("status", "").lower() in ("failed", "failure", "warning", "warn")
        ]
        seen_tests = set()
        unique_results = []
        for tr in failed_warning:
            test_name = (tr.get("test") or {}).get("name", "") if isinstance(tr.get("test"), dict) else ""
            if not test_name or test_name in seen_tests:
                continue
            seen_tests.add(test_name)
            unique_results.append(tr)

        triage_genie_session = create_triage_genie_session()

        def process_one(tr):
            try:
                test_field = tr.get("test", {})
                testcase_name = (test_field.get("name", "") if isinstance(test_field, dict) else
                                str(test_field) if test_field else "")
                status = tr.get("status", "Failed")
                jira_tickets = tr.get("jira_tickets", [])
                jira_ticket = (jira_tickets[0] if jira_tickets else "") or ""
                if isinstance(jira_ticket, dict):
                    jira_ticket = jira_ticket.get("$oid", "") or str(jira_ticket)
                jira_ticket = str(jira_ticket).strip() if jira_ticket else ""

                testcase_id = None
                if isinstance(tr.get("_id"), dict) and "$oid" in tr.get("_id", {}):
                    testcase_id = tr["_id"]["$oid"]
                else:
                    testcase_id = str(tr.get("_id", "")) if tr.get("_id") else ""

                triage_genie_ticket = ""
                if testcase_id and triage_genie_session:
                    try:
                        tg = fetch_triage_genie_ticket_id(testcase_id, triage_session=triage_genie_session)
                        if tg:
                            triage_genie_ticket = str(tg).strip()
                    except Exception as tg_err:
                        logger.debug(f"Triage Genie lookup failed for {testcase_id}: {tg_err}")

                if jira_ticket and triage_genie_ticket:
                    match_status = "Matched" if jira_ticket.upper() == triage_genie_ticket.upper() else "Unmatched"
                else:
                    match_status = "N/A" if not jira_ticket and not triage_genie_ticket else ("" if not (jira_ticket and triage_genie_ticket) else "N/A")

                regression_owner = resolve_owner(testcase_name) if testcase_name else "Unknown"
                return {
                    "testcase_name": testcase_name,
                    "regression_owner": regression_owner,
                    "status": status,
                    "triage_genie_ticket": triage_genie_ticket,
                    "jira_ticket": jira_ticket,
                    "match_status": match_status,
                }
            except Exception as e:
                logger.warning(f"Error processing test result for triage accuracy: {e}")
                return None

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            raw = list(executor.map(process_one, unique_results))
            testcases = [tc for tc in raw if tc is not None]

        total = len(testcases)
        triaged_count = sum(1 for tc in testcases if tc.get("jira_ticket"))
        # Triage Genie % = among triaged (JITA tagged), how many have Triage Genie ticket
        triage_genie_count = sum(1 for tc in testcases if tc.get("jira_ticket") and tc.get("triage_genie_ticket"))
        # Total Triage Genie Tagged = among ALL failed/warning, how many have Triage Genie ticket
        total_triage_genie_count = sum(1 for tc in testcases if tc.get("triage_genie_ticket"))
        matched_count = sum(1 for tc in testcases if tc.get("match_status") == "Matched")
        unmatched_count = sum(1 for tc in testcases if tc.get("match_status") == "Unmatched")

        triage_completed_percent = round(100 * triaged_count / total, 1) if total else 0
        triage_genie_percent = round(100 * triage_genie_count / triaged_count, 1) if triaged_count else 0
        total_triage_genie_percent = round(100 * total_triage_genie_count / total, 1) if total else 0
        denom = matched_count + unmatched_count
        matched_percent = round(100 * matched_count / denom, 1) if denom else 0
        unmatched_percent = round(100 * unmatched_count / denom, 1) if denom else 0

        result = {
            "generated_time": datetime.utcnow().isoformat(),
            "tag": tag if tag else None,
            "task_ids": collected_task_ids,
            "testcases": testcases,
            "triage_summary": {
                "total_failed_warning_count": total,
                "triaged_count": triaged_count,
                "triage_genie_count": triage_genie_count,
                "total_triage_genie_count": total_triage_genie_count,
                "triage_completed_percent": triage_completed_percent,
                "triage_genie_percent": triage_genie_percent,
                "total_triage_genie_percent": total_triage_genie_percent,
                "matched_count": matched_count,
                "unmatched_count": unmatched_count,
                "matched_percent": matched_percent,
                "unmatched_percent": unmatched_percent,
            },
        }
        save_triage_accuracy_data(result, cache_tag)
        logger.info(f"[END] Triage Accuracy | testcases={len(testcases)} | time={time.time() - start:.2f}s")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in triage accuracy: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/mcp/regression/triage-accuracy/export-excel", methods=["GET"])
@app.route("/api/mcp/regression/triage-accuracy/export-excel", methods=["GET"])
def export_triage_accuracy_excel():
    """Export triage accuracy data as Excel file."""
    try:
        tag = request.args.get("tag")
        if not tag:
            config = load_regression_config()
            if config.get("input_mode") == "tag":
                tag = config.get("default_tag") or config.get("tag") or ""
        cache_tag = tag if tag else None
        data = load_triage_accuracy_data(cache_tag)
        if not data or not isinstance(data, dict):
            return jsonify({"error": "No triage accuracy data available. Load Triage Accuracy Analyzer first."}), 404

        testcases = data.get("testcases", [])
        triage_summary = data.get("triage_summary", {})

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            # Sheet 1: Triage Analysis
            df_analysis = pd.DataFrame(testcases, columns=[
                "testcase_name", "regression_owner", "status",
                "triage_genie_ticket", "jira_ticket", "match_status"
            ])
            df_analysis.columns = [
                "Testcase Name", "Regression Owner", "Status",
                "Triage Genie Ticket", "Jira Ticket", "Matched/Unmatched"
            ]
            df_analysis.to_excel(writer, sheet_name="Triage Analysis", index=False)

            # Sheet 2: Triage Summary (Metric, Count, Percentage)
            tg_count = triage_summary.get("triage_genie_count", 0)
            matched = triage_summary.get("matched_count", 0)
            unmatched = triage_summary.get("unmatched_count", 0)
            summary_rows = [
                ("Triage Genie Ticket %(based on completed triaged)", tg_count, triage_summary.get("triage_genie_percent", 0)),
                ("Matched %", matched, triage_summary.get("matched_percent", 0)),
                ("Unmatched %", unmatched, triage_summary.get("unmatched_percent", 0)),
            ]
            df_summary = pd.DataFrame(summary_rows, columns=["Metric", "Count", "Percentage"])
            df_summary.to_excel(writer, sheet_name="Triage Summary", index=False)

        output.seek(0)
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="triage_accuracy_report.xlsx",
        )
    except Exception as e:
        logger.error(f"Error exporting triage accuracy Excel: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------
# QI Summary Report Endpoint
# ---------------------------------------------------
@app.route("/mcp/regression/qi-summary", methods=["GET"])
def get_qi_summary():
    start = time.time()
    tag = request.args.get("tag")
    task_ids_param = request.args.get("task_ids")  # Comma-separated task IDs
    
    # Parse task_ids if provided
    task_ids = None
    if task_ids_param:
        task_ids = [tid.strip() for tid in task_ids_param.split(",") if tid.strip()]
    
    if not tag and not task_ids:
        return jsonify({"error": "Either tag or task_ids is required"}), 400
    
    if tag:
        logger.info(f"[START] QI Summary | tag={tag}")
    else:
        logger.info(f"[START] QI Summary | task_ids={len(task_ids)} tasks")
    
    try:
        # Fetch tasks for the tag or task IDs
        tasks = fetch_regression_tasks(tag=tag, task_ids=task_ids)
        
        # Collect all task IDs from fetched tasks
        collected_task_ids = [task["_id"]["$oid"] for task in tasks]
        
        # Fetch test results using agave_test_results API for accurate counts
        logger.info(f"Fetching test results for {len(collected_task_ids)} tasks using agave_test_results API")
        test_results = []
        if collected_task_ids:
            try:
                test_results = fetch_test_results_batch_with_pagination(collected_task_ids)
                logger.info(f"Fetched {len(test_results)} test results")
            except Exception as e:
                logger.warning(f"Failed to fetch test results from agave_test_results API: {e}. Falling back to test_result_count.")
                test_results = []
        
        # Group test results by task_id and branch
        test_results_by_task = defaultdict(list)
        task_branch_map = {}
        for task in tasks:
            task_id = task["_id"]["$oid"]
            branch = task.get("branch", "unknown")
            task_branch_map[task_id] = branch
        
        for test_result in test_results:
            agave_task_id = test_result.get("agave_task_id")
            if agave_task_id:
                # Handle both string and $oid format
                if isinstance(agave_task_id, dict) and "$oid" in agave_task_id:
                    task_id = agave_task_id["$oid"]
                else:
                    task_id = str(agave_task_id)
                if task_id in task_branch_map:
                    test_results_by_task[task_id].append(test_result)
        
        # Generate QI Summary Report
        summary = {
            "tag": tag or None,
            "task_ids": collected_task_ids if collected_task_ids else None,
            "generated_at": datetime.utcnow().isoformat(),
            "total_tasks": len(tasks),
            "status_summary": {
                "testing": 0,
                "completed": 0,
                "pending": 0,
                "failed": 0
            },
            "test_summary": {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "pending": 0,
                "warning": 0,
                "running": 0,
                "skipped": 0,
                "killed": 0
            },
            "branch_summary": {}
        }
        
        for task in tasks:
            task_id = task["_id"]["$oid"]
            status = task.get("status", "").lower()
            branch = task.get("branch", "unknown")
            
            # Count test statuses from agave_test_results if available
            task_test_counts = {
                "total": 0,
                "Succeeded": 0,
                "Failed": 0,
                "Pending": 0,
                "Warning": 0,
                "Running": 0,
                "Skipped": 0,
                "Killed": 0
            }
            
            if task_id in test_results_by_task:
                # Count statuses from actual test results
                for test_result in test_results_by_task[task_id]:
                    test_status = test_result.get("status", "")
                    task_test_counts["total"] += 1
                    
                    # Normalize status names (handle case-insensitive matching)
                    status_lower = test_status.lower() if test_status else ""
                    
                    if status_lower == "succeeded" or status_lower == "success":
                        task_test_counts["Succeeded"] += 1
                    elif status_lower == "failed" or status_lower == "failure":
                        task_test_counts["Failed"] += 1
                    elif status_lower == "pending" or status_lower == "waiting":
                        task_test_counts["Pending"] += 1
                    elif status_lower == "warning" or status_lower == "warn":
                        task_test_counts["Warning"] += 1
                    elif status_lower == "running" or status_lower == "executing" or status_lower == "in_progress":
                        task_test_counts["Running"] += 1
                    elif status_lower == "skipped" or status_lower == "skip":
                        task_test_counts["Skipped"] += 1
                    elif status_lower == "killed" or status_lower == "terminated" or status_lower == "cancelled":
                        task_test_counts["Killed"] += 1
                    else:
                        # For unknown statuses, try to infer from common patterns
                        if any(x in status_lower for x in ["pending", "waiting", "queued"]):
                            task_test_counts["Pending"] += 1
                        elif any(x in status_lower for x in ["running", "executing", "in_progress", "active"]):
                            task_test_counts["Running"] += 1
                        elif any(x in status_lower for x in ["skipped", "skip"]):
                            task_test_counts["Skipped"] += 1
                        elif any(x in status_lower for x in ["killed", "terminated", "cancelled", "aborted"]):
                            task_test_counts["Killed"] += 1
                        else:
                            # Default to pending only if truly unknown
                            task_test_counts["Pending"] += 1
            else:
                # Fallback to test_result_count if agave_test_results not available
                tc = task.get("test_result_count", {})
                task_test_counts = {
                    "total": tc.get("Total", 0),
                    "Succeeded": tc.get("Succeeded", 0),
                    "Failed": tc.get("Failed", 0),
                    "Pending": tc.get("Pending", 0),
                    "Warning": tc.get("Warning", 0),
                    "Running": tc.get("Running", 0),
                    "Skipped": tc.get("Skipped", 0),
                    "Killed": tc.get("Killed", 0)
                }
            
            # Status summary
            if status == "testing":
                summary["status_summary"]["testing"] += 1
            elif status == "pending":
                summary["status_summary"]["pending"] += 1
            elif task_test_counts["Failed"] > 0:
                summary["status_summary"]["failed"] += 1
            else:
                summary["status_summary"]["completed"] += 1
            
            # Test summary (aggregate across all tasks)
            summary["test_summary"]["total"] += task_test_counts["total"]
            summary["test_summary"]["succeeded"] += task_test_counts["Succeeded"]
            summary["test_summary"]["failed"] += task_test_counts["Failed"]
            summary["test_summary"]["pending"] += task_test_counts["Pending"]
            summary["test_summary"]["warning"] += task_test_counts["Warning"]
            summary["test_summary"]["running"] += task_test_counts["Running"]
            summary["test_summary"]["skipped"] += task_test_counts["Skipped"]
            summary["test_summary"]["killed"] += task_test_counts["Killed"]
            
            # Branch summary
            if branch not in summary["branch_summary"]:
                summary["branch_summary"][branch] = {
                    "total_tasks": 0,
                    "total_tests": 0,
                    "failed_tests": 0
                }
            
            summary["branch_summary"][branch]["total_tasks"] += 1
            summary["branch_summary"][branch]["total_tests"] += task_test_counts["total"]
            summary["branch_summary"][branch]["failed_tests"] += task_test_counts["Failed"]
        
        logger.info(f"[END] QI Summary | time={time.time() - start:.2f}s")
        logger.info(f"Test Summary: {summary['test_summary']}")
        
        return jsonify(summary)
    except Exception as e:
        logger.error(f"Error in QI summary: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ======================================================
# Run Report - QI Analysis Endpoint
# ======================================================
def generate_qi_analysis(run_folder):
    """Generate QI analysis Excel file from CSV files in run folder"""
    try:
        # File paths
        tcms_csv_path = os.path.join(run_folder, 'tcms.csv')
        regression_owners_path = os.path.join(run_folder, 'regression_owners.csv')
        jita_csv_path = os.path.join(run_folder, 'jita.csv')
        tcms_bugs_csv_path = os.path.join(run_folder, 'tcms_bugs.csv')
        
        # Check if open-bugs.csv exists (alternative name)
        if not os.path.exists(tcms_bugs_csv_path):
            tcms_bugs_csv_path = os.path.join(run_folder, 'open-bugs.csv')
        
        # Validate required files exist
        required_files = {
            'tcms.csv': tcms_csv_path,
            'regression_owners.csv': regression_owners_path,
            'jita.csv': jita_csv_path,
            'tcms_bugs.csv or open-bugs.csv': tcms_bugs_csv_path
        }
        
        missing_files = [name for name, path in required_files.items() if not os.path.exists(path)]
        if missing_files:
            raise FileNotFoundError(f"Missing required files: {', '.join(missing_files)}")
        
        # Read CSV files
        logger.info("Reading CSV files...")
        df = pd.read_csv(tcms_csv_path)
        df_jita = pd.read_csv(jita_csv_path)
        df_o = pd.read_csv(regression_owners_path)
        tcms_bug_list = pd.read_csv(tcms_bugs_csv_path)
        
        # Process JITA data (remove Pending, handle duplicates)
        df_jita = df_jita[~df_jita.status.isin(['Pending'])]
        temp_df = df_jita[df_jita['start_time'] != "-"]
        if len(temp_df) > 0:
            temp_df.loc[:, 'start_time'] = pd.to_datetime(temp_df['start_time'], dayfirst=True)
            min_time = temp_df['start_time'].min()
            df_jita.loc[df_jita['start_time'] == '-', "start_time"] = min_time
            df_jita.loc[:, 'start_time'] = pd.to_datetime(df_jita['start_time'], dayfirst=True)
            df_jita = df_jita.sort_values(['start_time'], ascending=False).drop_duplicates(['name'])
        
        # Process TCMS data
        df['Test_Set'] = 'None'
        ll = []
        
        for index, row in df.iterrows():
            # Extract test set name
            if isinstance(row.get('Test Sets'), str):
                for testset in row['Test Sets'].split(','):
                    if re.search('test_sets/milestones/.*/cdp/.*/Regression_team_owned_lst', testset):
                        df.loc[index, 'Test_Set'] = testset.split('/')[-1]
                        break
            
            # Extract last passed ops
            if isinstance(row.get('Last Passed Ops'), str):
                parts = row['Last Passed Ops'].split('/')
                if len(parts) >= 2:
                    passed_ops = parts[0]
                    total_ops = parts[1].split('(')[0]
                    df.loc[index, 'last_passed_ops'] = passed_ops
                    df.loc[index, 'last_passed_total_ops'] = total_ops
            
            # Extract last run ops
            col_name = 'Last Run Ops'
            if isinstance(row.get(col_name), str):
                parts = row[col_name].split('/')
                if len(parts) >= 2:
                    passed_ops = parts[0]
                    total_ops = parts[1].split('(')[0]
                    df.loc[index, 'last_run_ops'] = int(passed_ops) if passed_ops.isdigit() else 0
                    df.loc[index, 'last_run_total_ops'] = int(total_ops) if total_ops.isdigit() else 0
                    if df.loc[index, 'last_run_total_ops'] > 0:
                        df.loc[index, 'last_run_qi'] = 100 * (df.loc[index, 'last_run_ops'] / df.loc[index, 'last_run_total_ops'])
                    else:
                        df.loc[index, 'last_run_qi'] = 0
                else:
                    df.loc[index, 'last_run_ops'] = 0
                    df.loc[index, 'last_run_total_ops'] = 0
                    df.loc[index, 'last_run_qi'] = 0
            else:
                df.loc[index, 'last_run_ops'] = 0
                df.loc[index, 'last_run_total_ops'] = 0
                df.loc[index, 'last_run_qi'] = 0
            
            # Extract test sets
            if isinstance(row.get('Test Sets'), str):
                test_sets = row['Test Sets'].split(',')
                for test_set in test_sets:
                    if re.search('test_sets/milestones/.*/cdp/.*/Regression_team_owned_lst/', test_set):
                        df.loc[index, 'Test_Set'] = test_set.split('/')[-1]
                        break
                    else:
                        df.loc[index, 'Test_Set'] = test_set.split('/')[-1]
            
            # Process open bugs
            if isinstance(row.get('Open Bugs'), str):
                bug_list = row['Open Bugs'].split(',')
                bugtype = tcms_bug_list[tcms_bug_list.Ticket.isin(bug_list)].groupby(['Type'])['Ticket'].count().to_dict()
                for key in bugtype.keys():
                    df.loc[index, f'{key}_bug_count'] = bugtype.get(key, 0)
                
                # Create bug-testcase mapping
                for bug in bug_list:
                    m = {
                        'bug_id': bug,
                        'test_case': row['Name'],
                        'last_run_qi': df.loc[index, 'last_run_qi'],
                        'last_run_ops': df.loc[index, 'last_run_ops'],
                        'last_run_total_ops': df.loc[index, 'last_run_total_ops'],
                        'Last Run Status': row.get('Last Run Status', '')
                    }
                    ll.append(m)
        
        df['last_run_ops'] = df['last_run_ops'].astype(int)
        df['last_run_total_ops'] = df['last_run_total_ops'].astype(int)
        
        df_bugs = pd.DataFrame(ll)
        
        # Extract test area
        testcasenames_split = df['Name'].str.split(pat='.', expand=True)
        t = testcasenames_split[[0, 1, 2, 3]].agg('.'.join, axis=1)
        df.insert(loc=1, column='Test Area', value=t)
        
        # Join with regression owners
        df = df.join(df_o.set_index('Test Area'), on='Test Area', how='left')
        
        nr_test_cases = df['Name'].count()
        
        def generate_qi_impact(df_data, colname, nr_test_cases):
            s1 = df_data.groupby([colname])['last_run_qi'].agg("mean").sort_values()
            s2 = df_data.groupby([colname])[colname].count()
            if colname == 'bug_id':
                s3 = df_bugs.groupby([colname, 'Last Run Status'])[[colname]].count().unstack()
                df_testarea = pd.concat([s1, s2, s3], axis=1)
            else:
                df_testarea = pd.concat([s1, s2], axis=1)
            cols = ['average_qi', 'nr_test_cases']
            cols.extend(df_testarea.columns[2:])
            df_testarea.columns = cols
            df_testarea['qi_impact'] = (df_testarea['average_qi'] - 100) * df_testarea['nr_test_cases']
            df_testarea['overall_qi_impact'] = 100 * (df_testarea['qi_impact'] / (100 * nr_test_cases))
            return df_testarea.sort_values(['overall_qi_impact'])
        
        df_testareas = generate_qi_impact(df, 'Test Area', nr_test_cases)
        df_bugid = generate_qi_impact(df_bugs, 'bug_id', nr_test_cases)
        
        # Process dates
        baseline_date = datetime.now() - timedelta(days=30)
        try:
            df.loc[:, 'Last Run Date'] = pd.to_datetime(df['Last Run Date'], format="%Y-%m-%d")
        except:
            df.loc[:, 'Last Run Date'] = pd.to_datetime(df['Last Run Date'])
        df = df.sort_values(['Last Run Date']).drop_duplicates(['Name'])
        
        df_tcms = df.copy()
        df_jita_tcms = df_jita.join(df.set_index('Name'), on='name', how='left')
        
        # Merge bugs with TCMS bug list
        tcms_bug_list['Name'] = tcms_bug_list['Ticket']
        del tcms_bug_list['Ticket']
        tcms_bug_qi = tcms_bug_list.join(df_bugid, on='Name', how='left')
        tcms_bug_qi['tcms_test_cases'] = tcms_bug_qi['nr_test_cases']
        del tcms_bug_qi['nr_test_cases']
        tcms_bug_qi = tcms_bug_qi.set_index(['Name'])
        
        # Generate output list for summary
        output_list = []
        output_list.append(f"Analysis ran on: {datetime.now()}")
        output_list.append(f"Total number of test cases: {df['Name'].count()}")
        output_list.append(f"Total number of test that passed in last run: {df[df['Last Run Status']=='succeeded']['Name'].count()}")
        output_list.append(f"Total number of test that failed in last run: {df[df['Last Run Status']=='failed']['Name'].count()}")
        output_list.append(f"Total number of test that warned in last run: {df[df['Last Run Status']=='warning']['Name'].count()}")
        output_list.append(f"Total number of test cases with bugs: {df[~df['Open Bugs'].isna()]['Name'].count()}")
        output_list.append(f"Last Run QI: {df['last_run_qi'].mean():.2f}")
        output_list.append(f"Total possible QI: {100*df['Name'].count():.0f}")
        output_list.append(f"Total QI of all test cases: {df[['last_run_qi']].sum().iloc[0]:.0f}")
        output_list.append(f"Total QI impacted due to bugs (overestimated): {df_bugid['qi_impact'].sum():.0f} in Percentage: {df_bugid['qi_impact'].sum()/(df['Name'].count()):.2f}%")
        output_list.append(f"Total number of bugs identified by the runs so far: {len(df_bugs['bug_id'].unique())}")
        output_list.append(f"Tests that never passed: {df[df['Last Passed Date'].isna()].count().iloc[0]}")
        output_list.append(f"Tests that never passed and have last_run_qi<50: {df[((df['Last Passed Date'].isna())&(df['last_run_qi']<50))].count().iloc[0]}")
        t = (100-(df[((df['Last Passed Date'].isna())&(df['last_run_qi']<50))]['last_run_qi'].sum()))*df[((df['Last Passed Date'].isna())&(df['last_run_qi']<50))].count().iloc[0]
        output_list.append(f"QI impact of tests that never passed and have last_run_qi<50: {t:.2f} in Percentage: {(t/df['Name'].count()):.2f}%")
        output_list.append(f"Failed tests with no open Bugs: {df_tcms[(df_tcms['Last Run Status'].isin(['failed','warning'])) & (df_tcms['Open Bugs'].isna())]['Name'].count()}")
        output_list.append(f"Failed tests that are not triaged (TCMS): {df[(df['Last Run Status'] != 'succeeded') & (df.get('Is Last Run Triaged', pd.Series([False]*len(df))) != True)]['Name'].count()}")
        
        # Generate Excel file
        filename = 'analysis_' + datetime.now().isoformat().replace(':', '_').replace('-', '_')
        xlsfilepath = os.path.join(run_folder, filename + '.xlsx')
        
        # Use openpyxl engine for writing
        with pd.ExcelWriter(xlsfilepath, engine='openpyxl') as writer:
            # Summary sheet
            pd.DataFrame(output_list).to_excel(writer, sheet_name='summary', startrow=0, startcol=0, index=False, header=False)
            
            # Bug QI Summary sheet
            tcms_bug_qi.groupby(['Type', 'Priority'])[['overall_qi_impact']].agg(['count', 'sum']).to_excel(
                writer, sheet_name='bug_qi_summary', startrow=0, startcol=0, index=True
            )
            
            # Bugs QI Analysis sheet
            tcms_bug_qi.sort_values(['overall_qi_impact']).to_excel(
                writer, sheet_name='bugs_qi_analysis', startrow=0, startcol=0, index=True
            )
        
        logger.info(f"Generated QI analysis file: {xlsfilepath}")
        return xlsfilepath
        
    except Exception as e:
        logger.error(f"Error generating QI analysis: {e}", exc_info=True)
        raise

@app.route("/mcp/regression/run-report/list-analysis-files", methods=["POST"])
def list_analysis_files():
    """List all analysis_*.xlsx files in a given directory"""
    try:
        req_data = request.json
        folder_path = req_data.get("folder_path")
        
        if not folder_path:
            return jsonify({"error": "folder_path is required"}), 400
        
        if not os.path.isdir(folder_path):
            return jsonify({"error": f"Folder path does not exist: {folder_path}"}), 400
        
        # Find all files matching analysis_*.xlsx pattern
        pattern = os.path.join(folder_path, "analysis_*.xlsx")
        matching_files = glob.glob(pattern)
        
        # Sort by modification time (newest first)
        matching_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        
        # Return just the filenames
        file_list = [os.path.basename(f) for f in matching_files]
        
        return jsonify({
            "success": True,
            "files": file_list,
            "folder_path": folder_path
        })
    except Exception as e:
        logger.error(f"Error listing analysis files: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

def read_existing_analysis_file(analysis_file_path):
    """Read and extract data from an existing analysis Excel file"""
    try:
        if not os.path.exists(analysis_file_path):
            raise FileNotFoundError(f"Analysis file not found: {analysis_file_path}")
        
        logger.info(f"Reading QI analysis from existing file: {analysis_file_path}")
        
        # Read Excel file sheets (same logic as in qi_analysis_from_folder)
        excel_data = {}
        
        # 1. Read summary sheet
        try:
            df_summary = pd.read_excel(analysis_file_path, sheet_name="summary", header=None)
            summary_text = "\n".join(df_summary[0].astype(str).tolist()) if len(df_summary.columns) > 0 else ""
            excel_data["summary"] = summary_text
        except Exception as e:
            logger.warning(f"Could not read summary sheet: {e}")
            excel_data["summary"] = ""
        
        # 2. Read bug_qi_summary sheet
        try:
            df_bug_qi_summary = pd.read_excel(analysis_file_path, sheet_name="bug_qi_summary", index_col=[0, 1], header=[0, 1])
            # Handle multi-level columns (from groupby with agg)
            bug_qi_summary_data = []
            type_totals = {}  # Track total impacting QI by type (test, product, framework, other)
            
            for (bug_type, priority), row in df_bug_qi_summary.iterrows():
                # Extract count and sum from multi-level columns
                count_val = 0
                sum_val = 0.0
                
                # Try to find count and sum columns
                for col in df_bug_qi_summary.columns:
                    if isinstance(col, tuple):
                        if 'overall_qi_impact' in str(col[0]).lower() or 'overall_qi_impact' in str(col):
                            if 'count' in str(col[1]).lower() or 'count' in str(col):
                                count_val = int(row[col]) if pd.notna(row[col]) else 0
                            elif 'sum' in str(col[1]).lower() or 'sum' in str(col):
                                sum_val = float(row[col]) if pd.notna(row[col]) else 0.0
                
                # Fallback: if columns are flattened
                if count_val == 0 and sum_val == 0.0:
                    for col in df_bug_qi_summary.columns:
                        col_str = str(col)
                        if 'count' in col_str.lower():
                            count_val = int(row[col]) if pd.notna(row[col]) else 0
                        elif 'sum' in col_str.lower():
                            sum_val = float(row[col]) if pd.notna(row[col]) else 0.0
                
                # Accumulate total by type
                type_str = str(bug_type).lower()
                if type_str not in type_totals:
                    type_totals[type_str] = 0.0
                type_totals[type_str] += sum_val
                
                bug_qi_summary_data.append({
                    "type": str(bug_type),
                    "priority": str(priority),
                    "testcase_count": count_val,
                    "impacting_qi": sum_val
                })
            
            # Calculate totals for test, product, framework, other
            type_summary = {
                "test": 0.0,
                "product": 0.0,
                "framework": 0.0,
                "other": 0.0
            }
            
            for type_key, total_val in type_totals.items():
                type_lower = type_key.lower()
                if 'test' in type_lower:
                    type_summary["test"] += total_val
                elif 'product' in type_lower:
                    type_summary["product"] += total_val
                elif 'framework' in type_lower:
                    type_summary["framework"] += total_val
                else:
                    type_summary["other"] += total_val
            
            excel_data["bug_qi_summary"] = bug_qi_summary_data
            excel_data["type_summary"] = type_summary
        except Exception as e:
            logger.warning(f"Could not read bug_qi_summary sheet: {e}")
            excel_data["bug_qi_summary"] = []
        
        # 3. Read bugs_qi_analysis sheet (Top QI Impacting bugs)
        try:
            df_bugs_qi_analysis = pd.read_excel(analysis_file_path, sheet_name="bugs_qi_analysis", index_col=0)
            # Sort by overall_qi_impact in ascending order (most negative/impactful first) and get top 30
            if "overall_qi_impact" in df_bugs_qi_analysis.columns:
                df_bugs_qi_analysis = df_bugs_qi_analysis.sort_values("overall_qi_impact", ascending=True).head(30)
            
            # Extract required columns
            top_bugs = []
            for bug_name, row in df_bugs_qi_analysis.iterrows():
                bug_data = {
                    "name": str(bug_name),
                    "type": str(row.get("Type", "")) if "Type" in row else "",
                    "priority": str(row.get("Priority", "")) if "Priority" in row else "",
                    "summary": str(row.get("Summary", "")) if "Summary" in row else "",
                    "assignee": str(row.get("Assignee", "")) if "Assignee" in row else "",
                    "impacted_tcs_latest_run": int(row.get("Impacted TCs (Latest Run)", 0)) if "Impacted TCs (Latest Run)" in row else 0,
                    "deferred": str(row.get("Deferred", "")) if "Deferred" in row else "",
                    "average_qi": float(row.get("average_qi", 0)) if "average_qi" in row else 0.0,
                    "overall_qi_impact": float(row.get("overall_qi_impact", 0)) if "overall_qi_impact" in row else 0.0
                }
                top_bugs.append(bug_data)
            
            excel_data["top_qi_impacting_bugs"] = top_bugs
        except Exception as e:
            logger.warning(f"Could not read bugs_qi_analysis sheet: {e}")
            excel_data["top_qi_impacting_bugs"] = []
        
        return excel_data
    except Exception as e:
        logger.error(f"Error reading existing analysis file: {e}", exc_info=True)
        raise

@app.route("/mcp/regression/run-report/qi-analysis", methods=["POST"])
def qi_analysis_from_folder():
    """Generate QI analysis Excel file and extract data from it, or read from existing file"""
    try:
        req_data = request.json
        run_folder = req_data.get("run_folder")
        analysis_file_name = req_data.get("analysis_file")  # Optional: if provided, use existing file
        
        if not run_folder:
            return jsonify({"error": "run_folder path is required"}), 400
        
        if not os.path.isdir(run_folder):
            return jsonify({"error": f"Folder path does not exist: {run_folder}"}), 400
        
        # If analysis_file is provided, read from existing file
        if analysis_file_name:
            analysis_file_path = os.path.join(run_folder, analysis_file_name)
            if not os.path.exists(analysis_file_path):
                return jsonify({"error": f"Analysis file not found: {analysis_file_name}"}), 400
            
            excel_data = read_existing_analysis_file(analysis_file_path)
            
            return jsonify({
                "success": True,
                "analysis_file": analysis_file_name,
                "run_folder": run_folder,
                "data": excel_data
            })
        
        # Otherwise, generate the analysis Excel file
        logger.info(f"Generating QI analysis for folder: {run_folder}")
        analysis_file = generate_qi_analysis(run_folder)
        
        # Read the generated file using the shared function
        excel_data = read_existing_analysis_file(analysis_file)
        
        return jsonify({
            "success": True,
            "analysis_file": os.path.basename(analysis_file),
            "run_folder": run_folder,
            "data": excel_data
        })
        
    except Exception as e:
        logger.error(f"Error reading QI analysis: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ======================================================
# Run Report - Email Endpoints
# ======================================================
@app.route("/mcp/regression/run-report/preview-email", methods=["POST"])
def preview_qi_bug_email():
    """Generate email preview for Top QI Impacting Bugs"""
    try:
        req_data = request.json
        bugs = req_data.get("bugs", [])
        branch_name = req_data.get("branch_name", "Unknown Branch")
        run_folder = req_data.get("run_folder", "")
        
        if not bugs or len(bugs) == 0:
            return jsonify({"error": "Bug data is required"}), 400
        
        # Collect unique assignees
        assignees = set()
        for bug in bugs:
            assignee = bug.get("assignee", "")
            if assignee:
                assignees.add(assignee)
        
        if not assignees:
            return jsonify({"error": "No assignees found in bug data"}), 400
        
        # Convert assignees to email format
        recipient_emails = []
        for assignee in assignees:
            if "@" in assignee:
                recipient_emails.append(assignee)
            else:
                recipient_emails.append(f"{assignee}@nutanix.com")
        
        # Create email subject
        subject = f"Top QI Impacting Bugs on {branch_name}"
        
        # Create email body with HTML table for all bugs
        bugs_table_rows = ""
        for idx, bug in enumerate(bugs, 1):
            bugs_table_rows += f"""
                <tr>
                    <td>{idx}</td>
                    <td>{bug.get('name', 'N/A')}</td>
                    <td>{bug.get('type', 'N/A')}</td>
                    <td>{bug.get('priority', 'N/A')}</td>
                    <td>{bug.get('summary', 'N/A')}</td>
                    <td>{bug.get('assignee', 'N/A')}</td>
                    <td>{bug.get('impacted_tcs_latest_run', 0)}</td>
                    <td>{bug.get('deferred', 'N/A')}</td>
                    <td>{bug.get('average_qi', 0):.2f}</td>
                    <td>{bug.get('overall_qi_impact', 0):.2f}</td>
                </tr>
            """
        
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .summary {{ margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-left: 4px solid #3498db; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 12px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #3498db; color: white; font-weight: bold; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
                tr:hover {{ background-color: #e8f4f8; }}
                .note {{ margin-top: 20px; padding: 15px; background-color: #fff3cd; border-left: 4px solid #ffc107; }}
            </style>
        </head>
        <body>
            <div class="summary">
                <h2>Top QI Impacting Bugs Notification</h2>
                <p>The following bugs have been identified as top QI impacting bugs on branch: <strong>{branch_name}</strong></p>
                <p><strong>Total Bugs:</strong> {len(bugs)}</p>
                <p><strong>Recipients:</strong> {', '.join(recipient_emails)}</p>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Bug Name</th>
                        <th>Type</th>
                        <th>Priority</th>
                        <th>Summary</th>
                        <th>Assignee</th>
                        <th>Impacted TCs</th>
                        <th>Deferred</th>
                        <th>Average QI</th>
                        <th>Overall QI Impact</th>
                    </tr>
                </thead>
                <tbody>
                    {bugs_table_rows}
                </tbody>
            </table>
            
            <div class="note">
                <p><strong>Note:</strong> These bugs impact more than 4 test cases and have significant overall QI impact. Please review and take appropriate action.</p>
                <p><strong>Run Folder:</strong> {run_folder}</p>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_body = f"""
Top QI Impacting Bugs Notification

The following bugs have been identified as top QI impacting bugs on branch: {branch_name}

Total Bugs: {len(bugs)}
Recipients: {', '.join(recipient_emails)}

Bug Details:
"""
        for idx, bug in enumerate(bugs, 1):
            text_body += f"""
{idx}. {bug.get('name', 'N/A')}
   - Type: {bug.get('type', 'N/A')}
   - Priority: {bug.get('priority', 'N/A')}
   - Summary: {bug.get('summary', 'N/A')}
   - Assignee: {bug.get('assignee', 'N/A')}
   - Impacted Test Cases: {bug.get('impacted_tcs_latest_run', 0)}
   - Deferred: {bug.get('deferred', 'N/A')}
   - Average QI: {bug.get('average_qi', 0):.2f}
   - Overall QI Impact: {bug.get('overall_qi_impact', 0):.2f}
"""
        
        text_body += f"""

Note: These bugs impact more than 4 test cases and have significant overall QI impact. Please review and take appropriate action.

Run Folder: {run_folder}
        """
        
        return jsonify({
            "success": True,
            "subject": subject,
            "html_body": html_body,
            "text_body": text_body,
            "recipients": recipient_emails,
            "bugs": bugs,
            "branch_name": branch_name,
            "run_folder": run_folder
        })
        
    except Exception as e:
        logger.error(f"Error in preview email: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-report/send-email", methods=["POST"])
def send_qi_bug_email():
    """Send email for Top QI Impacting Bugs"""
    try:
        req_data = request.json
        bugs = req_data.get("bugs", [])
        branch_name = req_data.get("branch_name", "Unknown Branch")
        run_folder = req_data.get("run_folder", "")
        recipients = req_data.get("recipients", [])
        
        if not bugs or len(bugs) == 0:
            return jsonify({"error": "Bug data is required"}), 400
        
        if not recipients or len(recipients) == 0:
            return jsonify({"error": "Recipients are required"}), 400
        
        # Create email subject
        subject = f"Top QI Impacting Bugs on {branch_name}"
        
        # Create email body with HTML table for all bugs
        bugs_table_rows = ""
        for idx, bug in enumerate(bugs, 1):
            bugs_table_rows += f"""
                <tr>
                    <td>{idx}</td>
                    <td>{bug.get('name', 'N/A')}</td>
                    <td>{bug.get('type', 'N/A')}</td>
                    <td>{bug.get('priority', 'N/A')}</td>
                    <td>{bug.get('summary', 'N/A')}</td>
                    <td>{bug.get('assignee', 'N/A')}</td>
                    <td>{bug.get('impacted_tcs_latest_run', 0)}</td>
                    <td>{bug.get('deferred', 'N/A')}</td>
                    <td>{bug.get('average_qi', 0):.2f}</td>
                    <td>{bug.get('overall_qi_impact', 0):.2f}</td>
                </tr>
            """
        
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .summary {{ margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-left: 4px solid #3498db; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 12px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #3498db; color: white; font-weight: bold; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
                tr:hover {{ background-color: #e8f4f8; }}
                .note {{ margin-top: 20px; padding: 15px; background-color: #fff3cd; border-left: 4px solid #ffc107; }}
            </style>
        </head>
        <body>
            <div class="summary">
                <h2>Top QI Impacting Bugs Notification</h2>
                <p>The following bugs have been identified as top QI impacting bugs on branch: <strong>{branch_name}</strong></p>
                <p><strong>Total Bugs:</strong> {len(bugs)}</p>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Bug Name</th>
                        <th>Type</th>
                        <th>Priority</th>
                        <th>Summary</th>
                        <th>Assignee</th>
                        <th>Impacted TCs</th>
                        <th>Deferred</th>
                        <th>Average QI</th>
                        <th>Overall QI Impact</th>
                    </tr>
                </thead>
                <tbody>
                    {bugs_table_rows}
                </tbody>
            </table>
            
            <div class="note">
                <p><strong>Note:</strong> These bugs impact more than 4 test cases and have significant overall QI impact. Please review and take appropriate action.</p>
                <p><strong>Run Folder:</strong> {run_folder}</p>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_body = f"""
Top QI Impacting Bugs Notification

The following bugs have been identified as top QI impacting bugs on branch: {branch_name}

Total Bugs: {len(bugs)}

Bug Details:
"""
        for idx, bug in enumerate(bugs, 1):
            text_body += f"""
{idx}. {bug.get('name', 'N/A')}
   - Type: {bug.get('type', 'N/A')}
   - Priority: {bug.get('priority', 'N/A')}
   - Summary: {bug.get('summary', 'N/A')}
   - Assignee: {bug.get('assignee', 'N/A')}
   - Impacted Test Cases: {bug.get('impacted_tcs_latest_run', 0)}
   - Deferred: {bug.get('deferred', 'N/A')}
   - Average QI: {bug.get('average_qi', 0):.2f}
   - Overall QI Impact: {bug.get('overall_qi_impact', 0):.2f}
"""
        
        text_body += f"""

Note: These bugs impact more than 4 test cases and have significant overall QI impact. Please review and take appropriate action.

Run Folder: {run_folder}
        """
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = os.getenv('SMTP_FROM_EMAIL', 'regression-dashboard@nutanix.com')
        msg['To'] = ', '.join(recipients)
        
        # Add both plain text and HTML versions
        part1 = MIMEText(text_body, 'plain')
        part2 = MIMEText(html_body, 'html')
        
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email using SMTP
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.nutanix.com')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_user = os.getenv('SMTP_USER', '')
        smtp_password = os.getenv('SMTP_PASSWORD', '')
        
        try:
            # For now, we'll just log the email instead of actually sending it
            # Uncomment the SMTP code below when SMTP credentials are configured
            logger.info(f"Email prepared for {', '.join(recipients)}:")
            logger.info(f"Subject: {subject}")
            logger.info(f"Number of bugs: {len(bugs)}")
            logger.info(f"Body length: {len(text_body)} chars")
            
            # Uncomment below to actually send email:
            # with smtplib.SMTP(smtp_server, smtp_port) as server:
            #     if smtp_user and smtp_password:
            #         server.starttls()
            #         server.login(smtp_user, smtp_password)
            #     server.send_message(msg)
            
            return jsonify({
                "success": True,
                "message": f"Email prepared for {len(recipients)} recipient(s)",
                "recipients": recipients,
                "note": "Email sending is currently logged. Configure SMTP settings to enable actual email sending."
            })
        except Exception as e:
            logger.error(f"Error sending email: {e}", exc_info=True)
            return jsonify({"error": f"Failed to send email: {str(e)}"}), 500
        
    except Exception as e:
        logger.error(f"Error in send email: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ======================================================
# Run Plan Endpoints
# ======================================================

# JITA Authentication
from base64 import b64decode

def safe_b64decode(s):
    """Safely decode base64 string, adding padding if needed"""
    # Add padding if needed (base64 strings must be multiple of 4)
    missing_padding = len(s) % 4
    if missing_padding:
        s += '=' * (4 - missing_padding)
    return b64decode(s).decode("utf-8")

# Service account credentials for batch operations (matching reference script)
JITA_SVC_USERNAME = safe_b64decode("c3ZjLmNkcC5yZWdyZXNzaW9u")
JITA_SVC_PASSWORD = safe_b64decode("Knh0WTFtNiYlVko0akZXZzJlZHY=")
JITA_SVC_AUTH = (JITA_SVC_USERNAME, JITA_SVC_PASSWORD)

# User credentials for triggering (matching reference script)
JITA_USERNAME = safe_b64decode("c3VkaGFyc2hhbi5tdXNhbGk=")
JITA_PASSWORD = safe_b64decode("V29ya291dEAy")
JITA_AUTH = (JITA_USERNAME, JITA_PASSWORD)

# Helper function to update tester_tags for job profiles
def update_job_profiles_tester_tags(job_profile_ids, tag_name, action="add"):
    """
    Update tester_tags for multiple job profiles
    action: "add" to append tag, "remove" to remove tag
    """
    updated_count = 0
    failed_updates = []
    
    def update_single_job_tags(job_id):
        try:
            # Fetch existing profile
            get_url = f"{JITA_BASE}/job_profiles/{job_id}"
            get_resp = requests.get(get_url, headers={"Content-Type": "application/json"}, auth=JITA_SVC_AUTH, verify=False, timeout=30)
            
            if get_resp.status_code != 200:
                return {"job_id": job_id, "success": False, "error": f"Failed to fetch: {get_resp.status_code}"}
            
            existing_profile = get_resp.json().get("data", {})
            if not existing_profile:
                return {"job_id": job_id, "success": False, "error": "Empty profile data"}
            
            updated_profile = existing_profile.copy()
            tester_tags = existing_profile.get("tester_tags", [])
            
            if not isinstance(tester_tags, list):
                tester_tags = []
            
            if action == "add":
                # Add tag if not already present
                if tag_name not in tester_tags:
                    tester_tags.append(tag_name)
                    updated_profile["tester_tags"] = tester_tags
                else:
                    return {"job_id": job_id, "success": True, "message": "Tag already exists"}
            elif action == "remove":
                # Remove tag if present
                if tag_name in tester_tags:
                    tester_tags.remove(tag_name)
                    updated_profile["tester_tags"] = tester_tags
                else:
                    return {"job_id": job_id, "success": True, "message": "Tag not found"}
            
            # Ensure JSON serializable
            serializable_payload = {}
            for k, v in updated_profile.items():
                if isinstance(v, (set, tuple)):
                    serializable_payload[k] = list(v)
                elif v is Ellipsis:
                    serializable_payload[k] = None
                else:
                    serializable_payload[k] = v
            
            # PUT update
            put_resp = requests.put(
                f"{JITA_BASE}/job_profiles/{job_id}",
                headers={"Content-Type": "application/json"},
                json=serializable_payload,
                auth=JITA_SVC_AUTH,
                verify=False,
                timeout=30
            )
            
            if put_resp.status_code == 200:
                resp_json = put_resp.json()
                if resp_json.get("success", True):
                    return {"job_id": job_id, "success": True}
                else:
                    return {"job_id": job_id, "success": False, "error": resp_json.get("message", "Update failed")}
            else:
                error_msg = put_resp.text[:200] if put_resp.text else f"HTTP {put_resp.status_code}"
                return {"job_id": job_id, "success": False, "error": error_msg}
        except Exception as e:
            logger.error(f"Exception updating tester_tags for {job_id}: {e}", exc_info=True)
            return {"job_id": job_id, "success": False, "error": str(e)}
    
    # Parallel execution
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(update_single_job_tags, jp_id) for jp_id in job_profile_ids]
        for future in as_completed(futures):
            result = future.result()
            if result["success"]:
                updated_count += 1
            else:
                failed_updates.append(result)
    
    return updated_count, failed_updates

@app.route("/mcp/regression/run-plan", methods=["GET"])
def list_run_plans():
    """List all run plans"""
    try:
        data = load_run_plans()
        return jsonify({"run_plans": data.get("run_plans", [])})
    except Exception as e:
        logger.error(f"Error listing run plans: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan", methods=["POST"])
def create_run_plan():
    """Create a new run plan"""
    try:
        req_data = request.json
        data = load_run_plans()
        
        # Validate tag name uniqueness
        tag_name = req_data.get("tag_name")
        for rp in data.get("run_plans", []):
            if rp.get("tag_name") == tag_name:
                return jsonify({"error": f"Tag name '{tag_name}' already exists"}), 400
        
        # Validate and filter job profiles
        job_profiles = req_data.get("job_profiles", [])
        # Filter out empty strings and invalid IDs
        job_profiles = [jp_id for jp_id in job_profiles if jp_id and isinstance(jp_id, str) and jp_id.strip()]
        
        if not job_profiles:
            return jsonify({"error": "At least one valid job profile is required"}), 400
        
        # Generate tag_name automatically if not provided
        tag_name = req_data.get("tag_name")
        if not tag_name:
            # Extract branch from name (e.g., CDP_Regression_Upgrade_master -> master)
            name_parts = req_data.get("name", "").split("_")
            branch = name_parts[-1] if name_parts else "master"
            timestamp = int(time.time() * 1000)
            tag_name = f"{branch}_{timestamp}"
        
        # Create new run plan
        new_id = str(int(time.time() * 1000))
        new_run_plan = {
            "id": new_id,
            "name": req_data.get("name"),
            "job_profiles": job_profiles,
            "tag_name": tag_name,
            "schedule_date": req_data.get("schedule_date"),
            "created_at": datetime.now().isoformat(),
            "last_triggered": None
        }
        
        data["run_plans"].append(new_run_plan)
        save_run_plans(data)
        
        # Append tag_name to tester_tags for all job profiles
        if tag_name and job_profiles:
            logger.info(f"Updating tester_tags for {len(job_profiles)} job profile(s) with tag: {tag_name}")
            updated_count, failed = update_job_profiles_tester_tags(job_profiles, tag_name, action="add")
            logger.info(f"Updated tester_tags: {updated_count} succeeded, {len(failed)} failed")
        
        return jsonify({"success": True, "run_plan": new_run_plan}), 201
    except Exception as e:
        logger.error(f"Error creating run plan: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/<run_plan_id>", methods=["PUT"])
def update_run_plan(run_plan_id):
    """Update an existing run plan"""
    try:
        req_data = request.json
        data = load_run_plans()
        
        # Find and update run plan
        for i, rp in enumerate(data.get("run_plans", [])):
            if rp.get("id") == run_plan_id:
                # Check if already triggered (restrict edits)
                if rp.get("last_triggered"):
                    # Only allow editing schedule_date, name, and tag_name
                    if "schedule_date" in req_data:
                        rp["schedule_date"] = req_data["schedule_date"]
                    if "name" in req_data:
                        rp["name"] = req_data["name"]
                    if "tag_name" in req_data:
                        # Validate uniqueness
                        tag_name = req_data["tag_name"]
                        for other_rp in data.get("run_plans", []):
                            if other_rp.get("id") != run_plan_id and other_rp.get("tag_name") == tag_name:
                                return jsonify({"error": f"Tag name '{tag_name}' already exists"}), 400
                        rp["tag_name"] = tag_name
                else:
                    # Full edit allowed before first trigger
                    rp["name"] = req_data.get("name", rp.get("name"))
                    
                    # Validate and filter job profiles if provided
                    if "job_profiles" in req_data:
                        new_job_profiles = req_data.get("job_profiles", [])
                        new_job_profiles = [jp_id for jp_id in new_job_profiles if jp_id and isinstance(jp_id, str) and jp_id.strip()]
                        if not new_job_profiles:
                            return jsonify({"error": "At least one valid job profile is required"}), 400
                        rp["job_profiles"] = new_job_profiles
                    
                    if "schedule_date" in req_data:
                        rp["schedule_date"] = req_data.get("schedule_date")
                
                save_run_plans(data)
                
                # Update tester_tags if job_profiles were updated
                # Tag name remains unchanged (auto-generated on create)
                tag_name = rp.get("tag_name")
                if "job_profiles" in req_data and tag_name:
                    job_profiles = rp.get("job_profiles", [])
                    job_profiles = [jp_id for jp_id in job_profiles if jp_id and isinstance(jp_id, str) and jp_id.strip()]
                    
                    if job_profiles:
                        logger.info(f"Ensuring tag '{tag_name}' exists in tester_tags for {len(job_profiles)} job profile(s)")
                        updated_count, failed = update_job_profiles_tester_tags(job_profiles, tag_name, action="add")
                        logger.info(f"Updated tester_tags: {updated_count} succeeded, {len(failed)} failed")
                
                return jsonify({"success": True, "run_plan": rp})
        
        return jsonify({"error": "Run plan not found"}), 404
    except Exception as e:
        logger.error(f"Error updating run plan: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/search-job-profiles", methods=["POST"])
def search_job_profiles():
    """Search job profiles by ID or pattern"""
    try:
        req_data = request.json
        search_type = req_data.get("search_type")  # 'id' or 'pattern'
        search_value = req_data.get("search_value")
        
        if not search_value:
            return jsonify({"error": "Search value is required"}), 400
        
        # Build raw_query based on search type
        if search_type == "id":
            # Comma-separated IDs
            ids = [id.strip() for id in search_value.split(",")]
            raw_query = {
                "_id": {"$in": [{"$oid": id} for id in ids]}
            }
        else:  # pattern
            raw_query = {
                "name": {
                    "$regex": f"^{search_value}",
                    "$options": "i"
                }
            }
        
        # Call JITA API
        # Note: JITA API expects raw_query as a URL-encoded JSON string in query params
        from urllib.parse import quote
        raw_query_str = quote(json.dumps(raw_query))
        params = {
            "raw_query": raw_query_str,
            "limit": 100
        }
        
        response = requests.get(
            f"{JITA_BASE}/job_profiles",
            params=params,
            auth=JITA_SVC_AUTH,
            verify=False,
            timeout=30
        )
        
        if response.status_code != 200:
            return jsonify({"error": f"JITA API error: {response.status_code}"}), 500
        
        result = response.json()
        job_profiles = result.get("data", [])
        
        return jsonify({"success": True, "job_profiles": job_profiles})
    except Exception as e:
        logger.error(f"Error searching job profiles: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/<run_plan_id>/trigger", methods=["POST"])
def trigger_run_plan(run_plan_id):
    """Trigger a run plan now"""
    try:
        logger.info(f"[START] Trigger Run Plan | run_plan_id={run_plan_id}")
        data = load_run_plans()
        
        # Find run plan
        run_plan = None
        for rp in data.get("run_plans", []):
            if rp.get("id") == run_plan_id:
                run_plan = rp
                break
        
        if not run_plan:
            logger.error(f"Run plan not found: {run_plan_id}")
            return jsonify({"error": "Run plan not found"}), 404
        
        logger.info(f"Found run plan: {run_plan.get('name')} (ID: {run_plan_id})")
        
        job_profile_ids = run_plan.get("job_profiles", [])
        logger.info(f"Original job_profiles from run plan: {job_profile_ids}")
        
        # Filter out empty strings and invalid IDs
        original_count = len(job_profile_ids)
        job_profile_ids = [jp_id for jp_id in job_profile_ids if jp_id and isinstance(jp_id, str) and jp_id.strip()]
        filtered_count = len(job_profile_ids)
        
        logger.info(f"Filtered job profiles: {original_count} -> {filtered_count} valid IDs")
        
        if not job_profile_ids:
            error_msg = f"Run plan '{run_plan.get('name')}' has no valid job profiles. Original list: {run_plan.get('job_profiles')}. Please add at least one valid job profile to the run plan."
            logger.error(error_msg)
            return jsonify({
                "error": error_msg,
                "run_plan_name": run_plan.get("name"),
                "original_job_profiles": run_plan.get("job_profiles"),
                "filtered_count": filtered_count
            }), 400
        
        logger.info(f"Triggering {filtered_count} job profile(s): {job_profile_ids}")
        
        # Trigger job profiles in parallel
        task_ids = []
        failed_jobs = []
        
        def trigger_single_job(job_id):
            try:
                if not job_id or not isinstance(job_id, str) or not job_id.strip():
                    return {"job_id": job_id, "success": False, "error": "Invalid job profile ID"}
                
                url = f"{JITA_BASE}/job_profiles/{job_id}/trigger"
                payload = {}
                headers = {"Content-Type": "application/json"}
                
                # Update NOS commit if provided (use service account for updates)
                if run_plan.get("nos_commit"):
                    # Fetch existing profile first
                    get_url = f"{JITA_BASE}/job_profiles/{job_id}"
                    get_resp = requests.get(get_url, headers=headers, auth=JITA_SVC_AUTH, verify=False, timeout=30)
                    if get_resp.status_code == 200:
                        existing_profile = get_resp.json().get("data", {})
                        if isinstance(existing_profile, dict):
                            build_selection = existing_profile.get("build_selection", {})
                            build_selection["commit_id"] = run_plan.get("nos_commit")
                            build_selection["by_commit_id"] = True
                            
                            # Update profile
                            update_payload = existing_profile.copy()
                            update_payload["build_selection"] = build_selection
                            
                            # Ensure JSON serializable
                            serializable_payload = {}
                            for k, v in update_payload.items():
                                if isinstance(v, (set, tuple)):
                                    serializable_payload[k] = list(v)
                                elif v is Ellipsis:
                                    serializable_payload[k] = None
                                else:
                                    serializable_payload[k] = v
                            
                            update_resp = requests.put(
                                f"{JITA_BASE}/job_profiles/{job_id}",
                                headers=headers,
                                json=serializable_payload,
                                auth=JITA_SVC_AUTH,
                                verify=False,
                                timeout=30
                            )
                            if update_resp.status_code != 200:
                                logger.warning(f"Failed to update commit for {job_id}: {update_resp.text[:200]}")
                
                # Trigger using user credentials (matching reference script)
                logger.info(f"Triggering Job Profile ID: {job_id}")
                resp = requests.post(
                    url,
                    headers=headers,
                    auth=JITA_AUTH,
                    json=payload,
                    verify=False,
                    timeout=60
                )
                
                if resp.status_code == 200:
                    try:
                        res_data = resp.json()
                        if res_data.get("success") and "task_ids" in res_data:
                            # Extract task IDs (matching reference script pattern)
                            ids = [item["$oid"] if isinstance(item, dict) and "$oid" in item else item for item in res_data["task_ids"]]
                            logger.info(f"✅ Triggered: {job_id} → Task ID(s): {ids}")
                            return {
                                "job_id": job_id,
                                "task_ids": ids,
                                "success": True
                            }
                        else:
                            error_msg = res_data.get("message", "Trigger failed") if isinstance(res_data, dict) else str(res_data)
                            logger.error(f"❌ Trigger failed for {job_id}: {error_msg}")
                            return {"job_id": job_id, "success": False, "error": error_msg}
                    except Exception as e:
                        logger.error(f"❌ Response parse error for {job_id}: {e}")
                        return {"job_id": job_id, "success": False, "error": f"Response parse error: {str(e)}"}
                else:
                    error_msg = resp.text[:200] if resp.text else f"HTTP {resp.status_code}"
                    logger.error(f"❌ HTTP {resp.status_code} → Failed to trigger job profile {job_id}: {error_msg}")
                    return {"job_id": job_id, "success": False, "error": f"HTTP {resp.status_code}: {error_msg}"}
            except Exception as e:
                logger.error(f"Exception in trigger_single_job for {job_id}: {e}", exc_info=True)
                return {"job_id": job_id, "success": False, "error": str(e)}
        
        # Parallel execution
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(trigger_single_job, jp_id) for jp_id in job_profile_ids]
            for future in as_completed(futures):
                result = future.result()
                if result["success"]:
                    task_ids.extend(result["task_ids"])
                else:
                    failed_jobs.append(result)
        
        # Update run plan
        for rp in data.get("run_plans", []):
            if rp.get("id") == run_plan_id:
                rp["last_triggered"] = datetime.now().isoformat()
                break
        
        # Save history
        history_entry = {
            "id": str(int(time.time() * 1000)),
            "run_plan_id": run_plan_id,
            "triggered_at": datetime.now().isoformat(),
            "task_ids": task_ids,
            "failed_jobs": failed_jobs,
            "status": "success" if not failed_jobs else "partial"
        }
        
        if "history" not in data:
            data["history"] = []
        data["history"].append(history_entry)
        
        save_run_plans(data)
        
        logger.info(f"[END] Trigger Run Plan | run_plan_id={run_plan_id} | task_ids={len(task_ids)} | failed={len(failed_jobs)}")
        
        return jsonify({
            "success": True,
            "task_ids": task_ids,
            "failed_jobs": failed_jobs,
            "total_triggered": len(task_ids),
            "total_failed": len(failed_jobs)
        })
    except Exception as e:
        logger.error(f"Error triggering run plan {run_plan_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/<run_plan_id>/batch-update", methods=["POST"])
def batch_update_job_profiles(run_plan_id):
    """Batch update job profiles in a run plan"""
    try:
        req_data = request.json
        data = load_run_plans()
        
        # Find run plan
        run_plan = None
        for rp in data.get("run_plans", []):
            if rp.get("id") == run_plan_id:
                run_plan = rp
                break
        
        if not run_plan:
            return jsonify({"error": "Run plan not found"}), 404
        
        job_profile_ids = run_plan.get("job_profiles", [])
        # Filter out empty strings and invalid IDs
        job_profile_ids = [jp_id for jp_id in job_profile_ids if jp_id and isinstance(jp_id, str) and jp_id.strip()]
        
        if not job_profile_ids:
            return jsonify({"error": "No valid job profiles in run plan"}), 400
        
        # Handle new components array structure or legacy single component structure
        components = req_data.get("components", [])
        if not components:
            # Legacy support: single component update
            component = req_data.get("component")
            if component:
                components = [{
                    "component": component,
                    "branch": req_data.get("branch", ""),
                    "update_type": req_data.get("update_type", ""),
                    "build_type": req_data.get("build_type", ""),
                    "tag": req_data.get("tag", ""),
                    "commit_id": req_data.get("commit_id", ""),
                    "gbn": req_data.get("gbn", "")
                }]
        
        updated_count = 0
        failed_updates = []
        
        def update_single_job(job_id):
            try:
                # Fetch existing profile (use service account for fetching)
                get_url = f"{JITA_BASE}/job_profiles/{job_id}"
                get_resp = requests.get(get_url, headers={"Content-Type": "application/json"}, auth=JITA_SVC_AUTH, verify=False, timeout=30)
                
                if get_resp.status_code != 200:
                    return {"job_id": job_id, "success": False, "error": f"Failed to fetch: {get_resp.status_code}"}
                
                existing_profile = get_resp.json().get("data", {})
                if not existing_profile:
                    return {"job_id": job_id, "success": False, "error": "Empty profile data"}
                
                # Start with full existing profile (like reference script)
                updated_profile = existing_profile.copy()
                
                # Process each component update
                for comp_data in components:
                    component = comp_data.get("component")
                    branch = comp_data.get("branch", "")
                    update_type = comp_data.get("update_type", "")
                    build_type = comp_data.get("build_type", "")
                    tag = comp_data.get("tag", "")
                    commit_id = comp_data.get("commit_id", "")
                    gbn = comp_data.get("gbn", "")
                    
                    if component == "NOS_CLUSTER":
                        # Update git.branch (always update if branch is provided, or preserve existing)
                        git = existing_profile.get("git", {})
                        if not git:
                            git = {"repo": "main"}
                        if branch:
                            git["branch"] = branch
                        git["repo"] = "main"  # Always ensure repo is "main"
                        updated_profile["git"] = git
                        
                        # Update build_selection (always update if update_type or build_type is provided)
                        if update_type or build_type:
                            build_selection = existing_profile.get("build_selection", {})
                            if not build_selection:
                                build_selection = {}
                            
                            # Always set build_type if provided
                            if build_type:
                                build_selection["build_type"] = build_type
                            
                            if update_type == "tag":
                                # By tag - always set these flags (reference shows they're always set)
                                build_selection["commit_must_be_newer"] = False
                                build_selection["by_latest_smoked"] = True
                                # Remove commit-related fields if they exist
                                build_selection.pop("by_commit_id", None)
                                build_selection.pop("commit_id", None)
                                build_selection.pop("gbn", None)
                            elif update_type == "commit":
                                # By commit - always set by_commit_id flag
                                build_selection["by_commit_id"] = True
                                # Remove tag-related fields if they exist
                                build_selection.pop("commit_must_be_newer", None)
                                build_selection.pop("by_latest_smoked", None)
                                
                                # Set commit_id and gbn if provided
                                if commit_id:
                                    build_selection["commit_id"] = commit_id
                                if gbn:
                                    # GBN should be an integer
                                    try:
                                        build_selection["gbn"] = int(gbn) if isinstance(gbn, str) else gbn
                                    except (ValueError, TypeError):
                                        build_selection["gbn"] = gbn
                            
                            updated_profile["build_selection"] = build_selection
                    
                    elif component == "PRISM_CENTRAL":
                        # Update PRISM_CENTRAL (following reference script pattern)
                        # Initialize resource_manager_json structure
                        resource_manager_json = existing_profile.get("resource_manager_json", {})
                        if not resource_manager_json:
                            resource_manager_json = {}
                        
                        PRISM_CENTRAL = resource_manager_json.get("PRISM_CENTRAL", {})
                        if not PRISM_CENTRAL:
                            PRISM_CENTRAL = {}
                        
                        PC_BUILD = PRISM_CENTRAL.get("build", {})
                        if not PC_BUILD:
                            PC_BUILD = {}
                        
                        # Update branch and component (if branch is provided)
                        if branch:
                            PC_BUILD["branch"] = branch
                        PC_BUILD["component"] = "main"  # Always set to "main"
                        
                        # Update build selection based on update_type
                        if update_type == "tag":
                            if tag:
                                PC_BUILD["build_selection_option"] = tag
                        elif update_type == "commit":
                            # For PRISM_CENTRAL, by commit uses build_selection_option for commit_id
                            if commit_id:
                                PC_BUILD["build_selection_option"] = commit_id
                            if gbn:
                                # GBN should be an integer
                                try:
                                    PC_BUILD["gbn"] = int(gbn) if isinstance(gbn, str) else gbn
                                except (ValueError, TypeError):
                                    PC_BUILD["gbn"] = gbn
                        
                        # Update build_selection_build_type if build_type is provided
                        if build_type:
                            PC_BUILD["build_selection_build_type"] = build_type
                        
                        # Always update PRISM_CENTRAL structure if component is selected
                        # This ensures the structure is properly initialized even if fields are optional
                        PRISM_CENTRAL["build"] = PC_BUILD
                        resource_manager_json["PRISM_CENTRAL"] = PRISM_CENTRAL
                        updated_profile["resource_manager_json"] = resource_manager_json
                
                # Update test framework branch if provided
                if req_data.get("nutest_branch"):
                    updated_profile["nutest-py3-tests_branch"] = req_data.get("nutest_branch")
                
                # Update test framework metadata (patch URLs and branch)
                if req_data.get("nutest_branch") or req_data.get("patch_url") or req_data.get("framework_patch_url"):
                    test_framework_metadata = existing_profile.get("test_framework_metadata", {})
                    if not test_framework_metadata:
                        test_framework_metadata = {"framework": {}, "test": {}}
                    
                    # Get existing metadata or create new (preserve existing values)
                    test_metadata = test_framework_metadata.get("test", {})
                    if not test_metadata:
                        test_metadata = {}
                    else:
                        # Preserve existing test metadata (branch, commit, etc.)
                        test_metadata = test_metadata.copy()
                    
                    framework_metadata = test_framework_metadata.get("framework", {})
                    if not framework_metadata:
                        framework_metadata = {}
                    else:
                        # Preserve existing framework metadata (branch, commit, etc.)
                        framework_metadata = framework_metadata.copy()
                    
                    # Update branch in both test and framework if nutest_branch is provided
                    if req_data.get("nutest_branch"):
                        test_metadata["branch"] = req_data.get("nutest_branch")
                        framework_metadata["branch"] = req_data.get("nutest_branch")
                    else:
                        # Preserve existing branch if not updating
                        if "branch" not in framework_metadata:
                            # Get from existing if available
                            existing_framework = test_framework_metadata.get("framework", {})
                            if existing_framework and "branch" in existing_framework:
                                framework_metadata["branch"] = existing_framework["branch"]
                    
                    # Update test patch URL if provided
                    if req_data.get("patch_url"):
                        test_metadata["patch_url"] = req_data.get("patch_url")
                    
                    # Update framework patch URL if provided
                    framework_patch_url = req_data.get("framework_patch_url")
                    if framework_patch_url:
                        framework_metadata["patch_url"] = framework_patch_url
                        logger.info(f"Updating framework patch_url to: {framework_patch_url}")
                    
                    # Ensure commit is preserved (set to null if not present, or preserve existing)
                    if "commit" not in framework_metadata:
                        existing_framework = test_framework_metadata.get("framework", {})
                        if existing_framework and "commit" in existing_framework:
                            framework_metadata["commit"] = existing_framework["commit"]
                        else:
                            framework_metadata["commit"] = None
                    if "commit" not in test_metadata:
                        existing_test = test_framework_metadata.get("test", {})
                        if existing_test and "commit" in existing_test:
                            test_metadata["commit"] = existing_test["commit"]
                        else:
                            test_metadata["commit"] = None
                    
                    test_framework_metadata["test"] = test_metadata
                    test_framework_metadata["framework"] = framework_metadata
                    updated_profile["test_framework_metadata"] = test_framework_metadata
                    logger.info(f"Updated test_framework_metadata: framework.patch_url={framework_metadata.get('patch_url')}, framework.branch={framework_metadata.get('branch')}")
                
                # Update tester_tags if provided (optional batch update)
                if req_data.get("tester_tags_action"):  # "add" or "remove"
                    tester_tags_action = req_data.get("tester_tags_action")
                    tester_tag_value = req_data.get("tester_tag_value", "")
                    
                    if tester_tag_value:
                        tester_tags = existing_profile.get("tester_tags", [])
                        if not isinstance(tester_tags, list):
                            tester_tags = []
                        
                        if tester_tags_action == "add":
                            # Add tag if not already present
                            if tester_tag_value not in tester_tags:
                                tester_tags.append(tester_tag_value)
                                updated_profile["tester_tags"] = tester_tags
                        elif tester_tags_action == "remove":
                            # Remove tag if present
                            if tester_tag_value in tester_tags:
                                tester_tags.remove(tester_tag_value)
                                updated_profile["tester_tags"] = tester_tags
                
                # Ensure JSON serializable (following reference script pattern)
                serializable_payload = {}
                for k, v in updated_profile.items():
                    if isinstance(v, (set, tuple)):
                        serializable_payload[k] = list(v)
                    elif v is Ellipsis:
                        serializable_payload[k] = None
                    else:
                        serializable_payload[k] = v
                
                # PUT update (use service account for batch updates)
                put_resp = requests.put(
                    f"{JITA_BASE}/job_profiles/{job_id}",
                    headers={"Content-Type": "application/json"},
                    json=serializable_payload,
                    auth=JITA_SVC_AUTH,
                    verify=False,
                    timeout=30
                )
                
                if put_resp.status_code == 200:
                    resp_json = put_resp.json()
                    if resp_json.get("success", True):
                        logger.info(f"Successfully updated job profile {job_id}")
                        return {"job_id": job_id, "success": True}
                    else:
                        error_msg = resp_json.get("message", "Update failed")
                        logger.error(f"Failed to update job profile {job_id}: {error_msg}")
                        return {"job_id": job_id, "success": False, "error": error_msg}
                else:
                    error_msg = put_resp.text[:500] if put_resp.text else f"HTTP {put_resp.status_code}"
                    logger.error(f"Failed to update job profile {job_id}: {error_msg}")
                    return {"job_id": job_id, "success": False, "error": error_msg}
            except Exception as e:
                logger.error(f"Exception updating job profile {job_id}: {e}", exc_info=True)
                return {"job_id": job_id, "success": False, "error": str(e)}
        
        # Parallel execution
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(update_single_job, jp_id) for jp_id in job_profile_ids]
            for future in as_completed(futures):
                result = future.result()
                if result["success"]:
                    updated_count += 1
                else:
                    failed_updates.append(result)
        
        return jsonify({
            "success": True,
            "updated_count": updated_count,
            "failed_updates": failed_updates
        })
    except Exception as e:
        logger.error(f"Error batch updating job profiles: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/<run_plan_id>/history", methods=["GET"])
def get_run_plan_history(run_plan_id):
    """Get history for a run plan"""
    try:
        data = load_run_plans()
        history = [
            entry for entry in data.get("history", [])
            if entry.get("run_plan_id") == run_plan_id
        ]
        # Sort by triggered_at descending
        history.sort(key=lambda x: x.get("triggered_at", ""), reverse=True)
        return jsonify({"history": history})
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/history/<history_id>/retry", methods=["POST"])
def retry_history_entry(history_id):
    """Retry a history entry trigger"""
    try:
        data = load_run_plans()
        
        # Find history entry
        history_entry = None
        for entry in data.get("history", []):
            if entry.get("id") == history_id:
                history_entry = entry
                break
        
        if not history_entry:
            return jsonify({"error": "History entry not found"}), 404
        
        # Trigger the run plan again
        run_plan_id = history_entry.get("run_plan_id")
        return trigger_run_plan(run_plan_id)
    except Exception as e:
        logger.error(f"Error retrying history entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/history/<history_id>", methods=["DELETE"])
def delete_history_entry(history_id):
    """Delete a history entry"""
    try:
        data = load_run_plans()
        
        # Remove history entry
        data["history"] = [
            entry for entry in data.get("history", [])
            if entry.get("id") != history_id
        ]
        
        save_run_plans(data)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error deleting history entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/<run_plan_id>/clone", methods=["POST"])
def clone_run_plan(run_plan_id):
    """Clone a run plan with a new unique tag_name"""
    try:
        data = load_run_plans()
        
        # Find run plan to clone
        source_run_plan = None
        for rp in data.get("run_plans", []):
            if rp.get("id") == run_plan_id:
                source_run_plan = rp
                break
        
        if not source_run_plan:
            return jsonify({"error": "Run plan not found"}), 404
        
        # Generate new unique tag_name
        # Extract branch from name (e.g., CDP_Regression_Upgrade_master -> master)
        name_parts = source_run_plan.get("name", "").split("_")
        branch = name_parts[-1] if name_parts else "master"
        timestamp = int(time.time() * 1000)
        new_tag_name = f"{branch}_{timestamp}"
        
        # Check for uniqueness (should be unique due to timestamp, but double-check)
        for rp in data.get("run_plans", []):
            if rp.get("tag_name") == new_tag_name:
                # If somehow duplicate, add random suffix
                new_tag_name = f"{branch}_{timestamp}_{random.randint(1000, 9999)}"
                break
        
        # Create cloned run plan
        new_id = str(int(time.time() * 1000))
        original_name = source_run_plan.get("name", "")
        cloned_name = f"{original_name}_clone" if original_name else "cloned_run_plan"
        
        cloned_run_plan = {
            "id": new_id,
            "name": cloned_name,
            "job_profiles": source_run_plan.get("job_profiles", []).copy(),
            "tag_name": new_tag_name,
            "schedule_date": source_run_plan.get("schedule_date"),
            "created_at": datetime.now().isoformat(),
            "last_triggered": None  # Reset trigger status
        }
        
        data["run_plans"].append(cloned_run_plan)
        save_run_plans(data)
        
        # Append new tag_name to tester_tags for all job profiles
        job_profiles = cloned_run_plan.get("job_profiles", [])
        job_profiles = [jp_id for jp_id in job_profiles if jp_id and isinstance(jp_id, str) and jp_id.strip()]
        
        if new_tag_name and job_profiles:
            logger.info(f"Updating tester_tags for {len(job_profiles)} job profile(s) with new tag: {new_tag_name}")
            updated_count, failed = update_job_profiles_tester_tags(job_profiles, new_tag_name, action="add")
            logger.info(f"Updated tester_tags: {updated_count} succeeded, {len(failed)} failed")
        
        return jsonify({
            "success": True,
            "run_plan": cloned_run_plan,
            "message": f"Run plan cloned successfully with new tag: {new_tag_name}"
        })
        
    except Exception as e:
        logger.error(f"Error cloning run plan: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/<run_plan_id>", methods=["DELETE"])
def delete_run_plan(run_plan_id):
    """Delete a run plan and all its associated history entries"""
    try:
        data = load_run_plans()
        
        # Find run plan
        run_plan = None
        for rp in data.get("run_plans", []):
            if rp.get("id") == run_plan_id:
                run_plan = rp
                break
        
        if not run_plan:
            return jsonify({"error": "Run plan not found"}), 404
        
        # Remove run plan from list
        data["run_plans"] = [
            rp for rp in data.get("run_plans", [])
            if rp.get("id") != run_plan_id
        ]
        
        # Remove all history entries associated with this run plan
        data["history"] = [
            entry for entry in data.get("history", [])
            if entry.get("run_plan_id") != run_plan_id
        ]
        
        save_run_plans(data)
        logger.info(f"Deleted run plan: {run_plan.get('name')} (ID: {run_plan_id})")
        
        return jsonify({"success": True, "message": f"Run plan '{run_plan.get('name')}' deleted successfully"})
    except Exception as e:
        logger.error(f"Error deleting run plan: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/<run_plan_id>/delete-tag", methods=["POST"])
def delete_tag_from_job_profiles(run_plan_id):
    """Delete a tag from tester_tags of all job profiles in a run plan"""
    try:
        req_data = request.json
        tag_name = req_data.get("tag_name")
        
        if not tag_name:
            return jsonify({"error": "Tag name is required"}), 400
        
        data = load_run_plans()
        
        # Find run plan
        run_plan = None
        for rp in data.get("run_plans", []):
            if rp.get("id") == run_plan_id:
                run_plan = rp
                break
        
        if not run_plan:
            return jsonify({"error": "Run plan not found"}), 404
        
        job_profile_ids = run_plan.get("job_profiles", [])
        # Filter out empty strings and invalid IDs
        job_profile_ids = [jp_id for jp_id in job_profile_ids if jp_id and isinstance(jp_id, str) and jp_id.strip()]
        
        if not job_profile_ids:
            return jsonify({"error": "No valid job profiles in run plan"}), 400
        
        logger.info(f"Removing tag '{tag_name}' from tester_tags for {len(job_profile_ids)} job profile(s)")
        updated_count, failed = update_job_profiles_tester_tags(job_profile_ids, tag_name, action="remove")
        
        return jsonify({
            "success": True,
            "updated_count": updated_count,
            "failed_updates": failed,
            "tag_name": tag_name
        })
    except Exception as e:
        logger.error(f"Error deleting tag: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/run-plan/tags", methods=["GET"])
def get_available_tags():
    """Get list of available tags from JITA"""
    try:
        # Fetch recent tasks to get unique tags
        params = {
            "limit": 1000,
            "only": "tester_tags"
        }
        
        response = session.get(
            f"{JITA_BASE}/tasks",
            params=params,
            auth=JITA_AUTH,
            timeout=30
        )
        
        if response.status_code != 200:
            return jsonify({"error": f"JITA API error: {response.status_code}"}), 500
        
        result = response.json()
        tasks = result.get("data", [])
        
        # Extract unique tags
        tags_set = set()
        for task in tasks:
            task_tags = task.get("tester_tags", [])
            tags_set.update(task_tags)
        
        tags_list = sorted(list(tags_set))
        return jsonify({"tags": tags_list})
    except Exception as e:
        logger.error(f"Error fetching tags: {e}")
        return jsonify({"error": str(e)}), 500

# ======================================================
# Triage Genie Endpoints
# ======================================================
@app.route("/mcp/regression/triage-genie/jobs", methods=["GET"])
def list_triage_genie_jobs():
    """List all Triage Genie jobs - primarily from JSON file"""
    try:
        # Load stored jobs from JSON file (primary source)
        stored_data = load_triage_genie_jobs()
        stored_jobs = stored_data.get("jobs", [])
        
        # Optionally fetch from API to update status for existing jobs
        # But prioritize stored jobs
        try:
            page = request.args.get("page", "1")
            per_page = request.args.get("per_page", "10")
            run_status = request.args.get("run_status", "")
            show_all = request.args.get("show_all", "true")
            name_search = request.args.get("name_search", "")
            
            timestamp = int(time.time() * 1000)
            url = f"{TRIAGE_GENIE_BASE}/jobs?page={page}&per_page={per_page}&run_status={run_status}&show_all={show_all}&name_search={name_search}&_={timestamp}"
            
            triage_token = os.getenv("TRIAGE_GENIE_TOKEN", "TOKEN")
            headers = {
                "Authorization": f"Bearer {triage_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers, verify=False, timeout=30)
            
            if response.status_code == 200:
                api_data = response.json()
                api_jobs = api_data.get("data", [])
                # Create a map of API jobs by ID for quick lookup
                api_jobs_map = {job.get("id"): job for job in api_jobs if job.get("id")}
                
                # Update stored jobs with latest status from API if available
                for stored_job in stored_jobs:
                    job_id = stored_job.get("id")
                    if job_id in api_jobs_map:
                        api_job = api_jobs_map[job_id]
                        # Update status fields but keep our stored data (name, jita_task_ids, etc.)
                        stored_job["run_status"] = api_job.get("run_status")
                        stored_job["triage_status"] = api_job.get("triage_status")
                        stored_job["last_check_time"] = api_job.get("last_check_time")
                        stored_job["last_check_status"] = api_job.get("last_check_status")
                        stored_job["last_check_triage_status"] = api_job.get("last_check_triage_status")
                        stored_job["last_check_review_status"] = api_job.get("last_check_review_status")
        except Exception as api_error:
            logger.warning(f"Failed to fetch from Triage Genie API: {api_error}, using stored jobs only")
        
        # Sort by ID descending (newest first)
        stored_jobs.sort(key=lambda x: x.get("id", 0), reverse=True)
        
        return jsonify({
            "success": True,
            "jobs": stored_jobs,
            "total": len(stored_jobs)
        })
            
    except Exception as e:
        logger.error(f"Error listing Triage Genie jobs: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/mcp/regression/triage-genie/jobs", methods=["POST"])
def create_triage_genie_job():
    """Create a new Triage Genie job"""
    try:
        req_data = request.json
        name = req_data.get("name")
        jita_task_ids = req_data.get("jita_task_ids")  # Comma-separated string
        skip_review = req_data.get("skip_review", False)
        created_by = req_data.get("created_by", "")
        
        if not name:
            return jsonify({"error": "Name is required"}), 400
        
        if not jita_task_ids:
            return jsonify({"error": "JITA task IDs are required"}), 400
        
        # Build payload
        payload = {
            "name": name,
            "jita_task_ids": jita_task_ids,
            "skip_review": skip_review,
            "created_by": created_by
        }
        
        # Get authorization token from environment or use default "TOKEN"
        # The API accepts "Bearer TOKEN" as a valid authentication header
        triage_token = os.getenv("TRIAGE_GENIE_TOKEN", "TOKEN")
        headers = {
            "Authorization": f"Bearer {triage_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{TRIAGE_GENIE_BASE}/jobs",
            headers=headers,
            json=payload,
            verify=False,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            data = response.json()
            # Handle different response structures
            if isinstance(data, dict):
                # Check if job is nested in response
                job_data = data.get("data") or data.get("job") or data
            else:
                job_data = {}
            
            # Always set name from request (ensure it's always present in stored data)
            # The name from the form should always be saved, even if API returns a different one
            job_data["name"] = name
            
            # Always set created_by from request
            if created_by:
                job_data["created_by"] = created_by
            
            # Always set jita_task_ids from request
            job_data["jita_task_ids"] = jita_task_ids
            
            # Convert jita_task_ids string to list and ensure jita_task_id_list is always set
            # Use API response if available, otherwise create from request
            if "jita_task_id_list" in job_data and job_data.get("jita_task_id_list"):
                # API already provided the list, use it
                pass
            else:
                # Create list from request jita_task_ids
                if isinstance(jita_task_ids, str):
                    job_data["jita_task_id_list"] = [tid.strip() for tid in jita_task_ids.split(",") if tid.strip()]
                elif isinstance(jita_task_ids, list):
                    job_data["jita_task_id_list"] = jita_task_ids
                else:
                    job_data["jita_task_id_list"] = []
            
            # Add created_at timestamp if not present
            if "create_time" not in job_data:
                job_data["create_time"] = datetime.now().isoformat()
            
            # Ensure skip_review is set
            job_data["skip_review"] = skip_review
            
            # Store job in JSON file
            stored_data = load_triage_genie_jobs()
            stored_jobs = stored_data.get("jobs", [])
            
            # Check if job already exists (by ID or name)
            job_id = job_data.get("id")
            job_name = job_data.get("name")
            
            # Remove existing job with same ID or name
            stored_jobs = [j for j in stored_jobs if j.get("id") != job_id and j.get("name") != job_name]
            
            # Add new job
            stored_jobs.append(job_data)
            stored_data["jobs"] = stored_jobs
            save_triage_genie_jobs(stored_data)
            
            logger.info(f"Triage Genie job created and stored: ID={job_id}, Name={job_name}")
            
            return jsonify({
                "success": True,
                "job": job_data
            })
        else:
            logger.error(f"Triage Genie API error: {response.status_code} - {response.text}")
            return jsonify({"error": f"Failed to create job: {response.status_code} - {response.text}"}), response.status_code
            
    except Exception as e:
        logger.error(f"Error creating Triage Genie job: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ======================================================
# Failed Testcase Analysis Endpoint
# ======================================================

# Constants for Jira and Glean APIs
JIRA_BASE = "https://jira.nutanix.com/rest/api/2"
GLEAN_BASE = "https://nutanix-be.glean.com/api/v1"

def get_jira_headers():
    """Get Jira API headers with authentication"""
    jira_token = os.getenv("JIRA_TOKEN", "")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jira_token}" if jira_token else ""
    }

def get_glean_headers():
    """Get Glean API headers with authentication"""
    glean_token = os.getenv("GLEAN_TOKEN", "")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {glean_token}" if glean_token else ""
    }

def fetch_jira_ticket(ticket_id):
    """Fetch Jira ticket details"""
    try:
        if not os.getenv("JIRA_TOKEN"):
            logger.warning("JIRA_TOKEN not set, skipping Jira API call")
            return None
        
        headers = get_jira_headers()
        resp = session.get(
            f"{JIRA_BASE}/issue/{ticket_id}",
            headers=headers,
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.warning(f"Failed to fetch Jira ticket {ticket_id}: {resp.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Error fetching Jira ticket {ticket_id}: {e}")
        return None

def search_glean(query_text):
    """Search Glean for similar issues"""
    try:
        if not os.getenv("GLEAN_TOKEN"):
            logger.warning("GLEAN_TOKEN not set, skipping Glean API call")
            return None
        
        headers = get_glean_headers()
        payload = {
            "query": query_text,
            "max_results": 5
        }
        resp = session.post(
            f"{GLEAN_BASE}/search",
            headers=headers,
            json=payload,
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.warning(f"Failed to search Glean: {resp.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Error searching Glean: {e}")
        return None

def determine_failure_stage(test_result):
    """Determine failure stage from test result"""
    # Try to extract from exception_summary or exception
    exception_summary = test_result.get("exception_summary", "").lower()
    exception = test_result.get("exception", "").lower()
    combined = f"{exception_summary} {exception}"
    
    if any(keyword in combined for keyword in ["setup", "set up", "before", "precondition"]):
        return "Test Setup"
    elif any(keyword in combined for keyword in ["teardown", "tear down", "after", "cleanup"]):
        return "Teardown"
    elif any(keyword in combined for keyword in ["infra", "infrastructure", "connection", "timeout", "network"]):
        return "Infra"
    else:
        return "Test Body"

# Intermittent (mark for rerun) patterns: loaded from JSON; if exception_summary
# matches any pattern, mark for rerun as Yes.
INTERMITTENT_PATTERNS_JSON = os.path.join(os.path.dirname(__file__), "intermittent_patterns.json")

def _load_intermittent_patterns():
    """Load intermittent regex patterns from JSON file."""
    default_patterns = [
        r"Timedout executing command source.*cluster start in .* secs with error:",
        r"Timedout executing command source.*cluster.*create in .* secs with error",
        r"Couldn't get handle to SVM VM object for ip",
    ]
    try:
        if os.path.exists(INTERMITTENT_PATTERNS_JSON):
            with open(INTERMITTENT_PATTERNS_JSON, "r") as f:
                data = json.load(f)
            raw = data.get("intermittent_patterns", data) if isinstance(data, dict) else data
            if isinstance(raw, list) and raw:
                return [re.compile(p, re.IGNORECASE) for p in raw]
    except Exception as e:
        logger.warning(f"Could not load intermittent_patterns.json: {e}, using defaults")
    return [re.compile(p, re.IGNORECASE) for p in default_patterns]

SETUP_EXC_LIST = _load_intermittent_patterns()

def is_intermittent_rerun(exception_summary):
    """If exception_summary matches setup_exc_list patterns, mark for rerun as Yes."""
    if not exception_summary:
        return "No"
    text = (exception_summary or "").strip()
    for pattern in SETUP_EXC_LIST:
        if pattern.search(text):
            return "Yes"
    return "No"

def classify_failure(exception_summary, exception, jira_data, glean_data):
    """Classify failure as Test Issue or Product Issue"""
    exception_lower = (exception_summary or "").lower() + " " + (exception or "").lower()
    
    # Test Issue indicators
    test_issue_keywords = [
        "assertion", "assert", "expected", "actual", "python", "import error",
        "syntax error", "indentation", "nameerror", "attributeerror", "typeerror",
        "test framework", "pytest", "unittest", "dependency", "library", "module not found"
    ]
    
    # Product Issue indicators
    product_issue_keywords = [
        "api", "backend", "server", "500", "503", "timeout", "connection refused",
        "feature", "regression", "bug", "defect", "broken", "not working"
    ]
    
    test_issue_score = sum(1 for keyword in test_issue_keywords if keyword in exception_lower)
    product_issue_score = sum(1 for keyword in product_issue_keywords if keyword in exception_lower)
    
    # Check Jira ticket if available
    if jira_data:
        jira_summary = jira_data.get("fields", {}).get("summary", "").lower()
        jira_description = jira_data.get("fields", {}).get("description", "").lower()
        jira_combined = f"{jira_summary} {jira_description}"
        
        if "test" in jira_combined and "fix" in jira_combined:
            test_issue_score += 2
        if "product" in jira_combined or "regression" in jira_combined:
            product_issue_score += 2
    
    if test_issue_score > product_issue_score and test_issue_score > 0:
        return "Test Issue"
    elif product_issue_score > test_issue_score and product_issue_score > 0:
        return "Product Issue"
    else:
        return "Unknown / Needs Manual Review"

def validate_triage_genie_ticket(jira_ticket_id, exception_summary, exception):
    """Validate Triage Genie / Jira ticket relevance"""
    if not jira_ticket_id:
        return "Invalid"
    
    jira_data = fetch_jira_ticket(jira_ticket_id)
    if not jira_data:
        return "Invalid"
    
    fields = jira_data.get("fields", {})
    ticket_status = fields.get("status", {}).get("name", "")
    resolution = fields.get("resolution", {}).get("name", "") if fields.get("resolution") else None
    summary = fields.get("summary", "").lower()
    description = fields.get("description", "").lower()
    
    # Check if ticket is resolved/closed
    if resolution or ticket_status in ["Closed", "Resolved", "Done"]:
        return "Invalid"
    
    # Compare exception with ticket description
    exception_lower = (exception_summary or "").lower() + " " + (exception or "").lower()
    ticket_text = f"{summary} {description}"
    
    # Check for keyword overlap
    exception_words = set(exception_lower.split())
    ticket_words = set(ticket_text.split())
    common_words = exception_words.intersection(ticket_words)
    
    if len(common_words) >= 3:
        return "Valid"
    elif len(common_words) >= 1:
        return "Partial"
    else:
        return "Invalid"

def generate_ai_suggestion(issue_type, exception_summary, exception, jira_tickets, jira_data, glean_data):
    """Generate AI suggestion based on analysis"""
    suggestions = []
    
    if issue_type == "Test Issue":
        exception_lower = (exception_summary or "").lower() + " " + (exception or "").lower()
        
        if "python" in exception_lower or "import" in exception_lower:
            suggestions.append("Failure caused by Python dependency or import issue. Update test dependencies and verify Python environment.")
        elif "assertion" in exception_lower or "assert" in exception_lower:
            suggestions.append("Assertion failure detected. Review expected vs actual values. Update test assertions if product behavior has changed.")
        elif "syntax" in exception_lower or "indentation" in exception_lower:
            suggestions.append("Syntax error in test code. Review and fix test script syntax.")
        else:
            suggestions.append("Test logic issue identified. Review test implementation and update test code. Consider creating a Nugerrit CR for test fixes.")
        
        if jira_tickets:
            suggestions.append(f"Review Jira ticket(s): {', '.join(jira_tickets)}")
    
    elif issue_type == "Product Issue":
        if jira_tickets and jira_data:
            ticket_id = jira_tickets[0]
            suggestions.append(f"Failure aligns with known product issue in {ticket_id}. Test behavior is valid. Monitor Jira ticket for fix.")
        elif jira_tickets:
            suggestions.append(f"Product regression detected. Track via Jira ticket(s): {', '.join(jira_tickets)}. Test should remain as-is until product fix.")
        else:
            suggestions.append("Product-level failure identified. Test behavior is valid. Consider creating a Jira ticket to track this product issue.")
        
        if glean_data:
            suggestions.append("Similar issues found in Glean search. Review related documentation or known issues.")
    
    else:
        suggestions.append("Unable to definitively classify failure. Manual review recommended. Check test logs and Jira tickets for context.")
        if jira_tickets:
            suggestions.append(f"Review existing Jira ticket(s): {', '.join(jira_tickets)}")
    
    return " ".join(suggestions)

def fetch_detailed_test_result(testcase_id):
    """Fetch detailed test result including exception and failure stage"""
    try:
        resp = session.get(
            f"{PHX_BASE}/agave_test_results/{testcase_id}",
            timeout=30
        )
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as e:
        logger.warning(f"Error fetching detailed test result {testcase_id}: {e}")
        return {}

def convert_testcase_name_to_path(testcase_name):
    """
    Convert testcase name to directory path.
    Example: cdp.curator.goldsuite_iointegrity.test_goldsuite.CuratorGoldSuiteTest.test_gold___cluster_upgrade_with_disk_balancing
    -> cdp/curator/goldsuite_iointegrity/test_goldsuite/CuratorGoldSuiteTest/test_gold___cluster_upgrade_with_disk_balancing
    """
    if not testcase_name:
        return ""
    # Replace dots with slashes
    path = testcase_name.replace(".", "/")
    return path

def fetch_log_from_url(log_url, timeout=30):
    """
    Fetch log content from a URL.
    Returns the log content as string, or empty string if fetch fails.
    """
    try:
        resp = session.get(log_url, timeout=timeout, verify=False)
        if resp.status_code == 200:
            return resp.text
        else:
            logger.warning(f"Failed to fetch log from {log_url}: HTTP {resp.status_code}")
            return ""
    except Exception as e:
        logger.warning(f"Error fetching log from {log_url}: {e}")
        return ""

def fetch_testcase_logs(testcase_name, tester_log_url):
    """
    Fetch steps.log and nutest_test.log for a testcase.
    
    Args:
        testcase_name: Full testcase name (e.g., cdp.curator.goldsuite_iointegrity.test_goldsuite.CuratorGoldSuiteTest.test_gold___cluster_upgrade_with_disk_balancing)
        tester_log_url: Base URL for logs directory (e.g., http://10.40.234.216/logs/...)
    
    Returns:
        dict with 'steps_log' and 'nutest_test_log' keys, containing log content or empty strings
    """
    logs = {
        "steps_log": "",
        "nutest_test_log": ""
    }
    
    if not testcase_name or not tester_log_url:
        return logs
    
    # Convert testcase name to path
    testcase_path = convert_testcase_name_to_path(testcase_name)
    if not testcase_path:
        return logs
    
    # Construct log URLs
    # Ensure tester_log_url ends with /
    base_url = tester_log_url.rstrip("/") + "/"
    
    # Construct full paths
    steps_log_url = f"{base_url}{testcase_path}/steps.log"
    nutest_test_log_url = f"{base_url}{testcase_path}/nutest_test.log"
    
    logger.info(f"Fetching logs for {testcase_name}")
    logger.debug(f"Steps log URL: {steps_log_url}")
    logger.debug(f"Nutest test log URL: {nutest_test_log_url}")
    
    # Fetch logs
    logs["steps_log"] = fetch_log_from_url(steps_log_url)
    logs["nutest_test_log"] = fetch_log_from_url(nutest_test_log_url)
    
    return logs

def generate_ai_failure_summary(exception, exception_summary, tester_log_url, testcase_name, steps_log="", nutest_test_log=""):
    """
    Generate AI-based failure summary using the Nutanix AI endpoint.
    
    Args:
        exception: Full exception text
        exception_summary: Exception summary
        tester_log_url: Base URL for logs
        testcase_name: Testcase name
        steps_log: Content of steps.log
        nutest_test_log: Content of nutest_test.log
    
    Returns:
        tuple (success: bool, summary: str or error message)
    """
    try:
        # Build the prompt content
        log_content = ""
        if steps_log:
            log_content += f"=== steps.log ===\n{steps_log[:5000]}\n\n"  # Limit to 5000 chars per log
        if nutest_test_log:
            log_content += f"=== nutest_test.log ===\n{nutest_test_log[:5000]}\n\n"
        
        # Build user content
        user_content = (
            f"Testcase: {testcase_name}\n\n"
            f"Exception Summary: {exception_summary or 'N/A'}\n\n"
            f"Exception:\n```\n{exception or 'N/A'}\n```\n\n"
        )
        
        if log_content:
            user_content += f"Test Logs:\n{log_content}\n"
        
        user_content += (
            "Provide a concise failure summary:\n"
            "(1) Root cause in one sentence\n"
            "(2) Failing component or line if clear\n"
            "(3) Suggested fix or next step"
        )
        
        # System prompt
        system_prompt = (
            "You are a test failure analyst. Given a Python test failure with exception details and logs, "
            "provide a concise failure summary: (1) Root cause in one sentence, (2) failing component or line if clear, "
            "(3) suggested fix or next step. Be specific and actionable."
        )
        
        # Prepare payload
        payload = {
            "model": "hack-reason",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 1024,
            "stream": False
        }
        
        # Make request to AI endpoint
        url = f"{AI_BASE}/chat/completions"
        headers = {
            "Authorization": f"Bearer {AI_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=60) as resp:
            if resp.getcode() != 200:
                return False, f"AI API returned HTTP {resp.getcode()}"
            
            response_data = json.loads(resp.read().decode())
            choices = response_data.get("choices", [])
            if not choices:
                return False, "AI returned no choices"
            
            content = (choices[0].get("message") or {}).get("content", "")
            return True, content.strip()
            
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            err_json = json.loads(body)
        except Exception:
            err_json = {"raw": body}
        return False, f"AI API error HTTP {e.code}: {json.dumps(err_json)[:300]}"
    except Exception as e:
        logger.error(f"Error generating AI failure summary: {e}", exc_info=True)
        return False, f"Error generating AI summary: {str(e)}"

def create_triage_genie_session():
    """
    Create a requests.Session authenticated via JITA login for Triage Genie API calls.
    Used by Failed Testcase Analysis when calling Triage Genie.
    """
    session_triage = requests.Session()
    session_triage.verify = False
    login_payload = {
        "username": JITA_USERNAME,
        "password": JITA_PASSWORD
    }
    try:
        login_response = session_triage.post(
            LOGIN_URL,
            data=login_payload,
            verify=False,
            timeout=15
        )
        if login_response.status_code != 200:
            logger.warning(f"Triage Genie login returned {login_response.status_code}, session may not be authenticated")
        return session_triage
    except Exception as e:
        logger.warning(f"Triage Genie login failed: {e}")
        return None


def fetch_triage_genie_ticket_id(agave_task_id, triage_session=None):
    """
    Fetch Triage Genie generated ticket ID using agave_task_id (testcase_id)
    
    Uses direct API call: GET /api/tasks/{testcase_id}
    Extracts dup_ticket_id from the response
    
    When triage_session is provided (e.g. from create_triage_genie_session()), uses
    login session for API calls; otherwise falls back to TRIAGE_GENIE_TOKEN.
    
    Returns:
        str: Jira ticket ID (e.g., "ENG-858029") or None if not found
    """
    if not agave_task_id:
        return None
    
    try:
        if triage_session:
            headers = {"Content-Type": "application/json"}
        else:
            triage_token = os.getenv("TRIAGE_GENIE_TOKEN", "TOKEN")
            headers = {
                "Authorization": f"Bearer {triage_token}",
                "Content-Type": "application/json"
            }
        
        # Approach 1: Direct task lookup using testcase_id
        # The testcase_id (agave_task_id) can be used directly as the Triage Genie task ID
        try:
            if triage_session:
                task_response = triage_session.get(
                    f"{TRIAGE_GENIE_BASE}/tasks/{agave_task_id}",
                    headers=headers,
                    verify=False,
                    timeout=15
                )
            else:
                task_response = requests.get(
                    f"{TRIAGE_GENIE_BASE}/tasks/{agave_task_id}",
                    headers=headers,
                    verify=False,
                    timeout=15
                )
            
            if task_response.status_code == 200:
                task_data = task_response.json()
                dup_ticket_id = task_data.get("dup_ticket_id")
                if dup_ticket_id:
                    logger.info(f"Found Triage Genie ticket {dup_ticket_id} for testcase_id {agave_task_id}")
                    return dup_ticket_id
            elif task_response.status_code == 404:
                logger.debug(f"Triage Genie task not found for testcase_id {agave_task_id}")
            else:
                logger.debug(f"Triage Genie API returned status {task_response.status_code} for testcase_id {agave_task_id}")
        
        except requests.exceptions.RequestException as e:
            logger.debug(f"Error in direct task lookup for testcase_id {agave_task_id}: {e}")
        
        # Approach 2: Fallback - Search through recent jobs if direct lookup fails
        # This is a backup method in case the testcase_id format doesn't match Triage Genie task ID
        try:
            if triage_session:
                jobs_response = triage_session.get(
                    f"{TRIAGE_GENIE_BASE}/jobs",
                    headers=headers,
                    params={"page": 1, "per_page": 20, "show_all": "true"},
                    verify=False,
                    timeout=15
                )
            else:
                jobs_response = requests.get(
                    f"{TRIAGE_GENIE_BASE}/jobs",
                    headers=headers,
                    params={"page": 1, "per_page": 20, "show_all": "true"},
                    verify=False,
                    timeout=15
                )
            
            if jobs_response.status_code == 200:
                jobs_data = jobs_response.json()
                jobs = jobs_data.get("jobs", []) or jobs_data.get("data", [])
                
                # Search through jobs to find matching task
                for job in jobs:
                    job_id = job.get("id") or job.get("_id")
                    if not job_id:
                        continue
                    
                    try:
                        if triage_session:
                            tasks_response = triage_session.get(
                                f"{TRIAGE_GENIE_BASE}/jobs/{job_id}/tasks",
                                headers=headers,
                                params={
                                    "page": 1,
                                    "per_page": 100
                                },
                                verify=False,
                                timeout=15
                            )
                        else:
                            tasks_response = requests.get(
                                f"{TRIAGE_GENIE_BASE}/jobs/{job_id}/tasks",
                                headers=headers,
                                params={
                                    "page": 1,
                                    "per_page": 100
                                },
                                verify=False,
                                timeout=15
                            )
                        
                        if tasks_response.status_code == 200:
                            tasks_data = tasks_response.json()
                            tasks = tasks_data.get("data", []) or tasks_data.get("tasks", [])
                            
                            # Find task with matching agave_task_id
                            for task in tasks:
                                task_agave_id = task.get("agave_task_id")
                                # Handle both string and object ID formats
                                if (task_agave_id == agave_task_id or 
                                    str(task_agave_id) == str(agave_task_id) or
                                    (isinstance(task_agave_id, dict) and task_agave_id.get("$oid") == agave_task_id)):
                                    dup_ticket_id = task.get("dup_ticket_id")
                                    if dup_ticket_id:
                                        logger.info(f"Found Triage Genie ticket {dup_ticket_id} for agave_task_id {agave_task_id} in job {job_id} (fallback method)")
                                        return dup_ticket_id
                    except Exception as e:
                        logger.debug(f"Error fetching tasks for job {job_id}: {e}")
                        continue
            
        except Exception as e:
            logger.debug(f"Error in fallback job search for Triage Genie lookup: {e}")
        
        return None
        
    except requests.exceptions.ConnectionError:
        logger.warning(f"Connection error fetching Triage Genie ticket for testcase_id {agave_task_id}")
        return None
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout fetching Triage Genie ticket for testcase_id {agave_task_id}")
        return None
    except Exception as e:
        logger.warning(f"Error fetching Triage Genie ticket for testcase_id {agave_task_id}: {e}")
        return None

@app.route("/mcp/regression/failed-analysis/analyze", methods=["GET"])
def analyze_failed_testcases():
    """Analyze failed testcases with AI agent"""
    start = time.time()
    
    tag = request.args.get("tag")
    task_ids_param = request.args.get("task_ids")
    include_param = request.args.get("include", "")
    include_set = {x.strip().lower() for x in include_param.split(",") if x.strip()} if include_param else set()
    # Default: basic + exception_summary + intermittent when no include given
    if not include_set:
        include_set = {"basic", "exception_summary", "intermittent"}
    
    # Parse task_ids if provided
    task_ids = None
    if task_ids_param:
        task_ids = [tid.strip() for tid in task_ids_param.split(",") if tid.strip()]
    
    if not tag and not task_ids:
        return jsonify({"error": "Either tag or task_ids is required"}), 400
    
    try:
        # Fetch regression tasks
        tasks = fetch_regression_tasks(tag=tag, task_ids=task_ids)
        if not tasks:
            return jsonify({
                "success": True,
                "results": [],
                "message": "No tasks found for the given criteria"
            })
        
        # Collect all task IDs
        collected_task_ids = [task["_id"]["$oid"] for task in tasks]
        
        # Fetch test results - only failed ones
        logger.info(f"Fetching failed test results for {len(collected_task_ids)} tasks")
        all_test_results = []
        
        if collected_task_ids:
            try:
                # Fetch all test results first
                all_results = fetch_test_results_batch_with_pagination(collected_task_ids)
                # Filter for failed tests
                failed_results = [
                    tr for tr in all_results 
                    if tr.get("status", "").lower() in ("failed", "failure")
                ]
                logger.info(f"Found {len(failed_results)} failed testcases")
                
                # Triage Genie session only when triage_genie_ticket requested
                triage_genie_session = create_triage_genie_session() if "triage_genie_ticket" in include_set else None
                
                # Current branch for history API (from first task)
                current_branch = (tasks[0].get("branch") or "") if tasks else ""
                
                # Analyze each failed testcase
                analysis_results = []
                
                for test_result in failed_results:
                    testcase_id = None
                    if isinstance(test_result.get("_id"), dict) and "$oid" in test_result.get("_id", {}):
                        testcase_id = test_result["_id"]["$oid"]
                    else:
                        testcase_id = str(test_result.get("_id", ""))
                    
                    # Fetch detailed test result for exception and failure stage
                    detailed_result = {}
                    if testcase_id:
                        detailed_result = fetch_detailed_test_result(testcase_id)
                    
                    # Extract data
                    test_field = test_result.get("test", {})
                    if isinstance(test_field, dict):
                        testcase_name = test_field.get("name", "")
                    elif isinstance(test_field, str):
                        testcase_name = test_field
                    else:
                        # Try from detailed result
                        detailed_test = detailed_result.get("test", {})
                        if isinstance(detailed_test, dict):
                            testcase_name = detailed_test.get("name", "")
                        elif isinstance(detailed_test, str):
                            testcase_name = detailed_test
                        else:
                            testcase_name = ""
                    
                    status = test_result.get("status", "FAILED")
                    exception_summary = test_result.get("exception_summary") or detailed_result.get("exception_summary", "")
                    exception = detailed_result.get("exception", "")
                    jira_tickets = test_result.get("jira_tickets", [])
                    test_log_url = test_result.get("test_log_url") or detailed_result.get("test_log_url", "")
                    comments = test_result.get("comments") or detailed_result.get("comments") or ""
                    
                    # Determine failure stage
                    failure_stage = determine_failure_stage({**test_result, **detailed_result})
                    
                    # Intermittent (mark for rerun) from exception_summary
                    intermittent_rerun = is_intermittent_rerun(exception_summary) if "intermittent" in include_set else None
                    
                    # Optional heavy fields: Jira/Glean, issue type, suggestion, Triage Genie ticket, AI Summary
                    jira_data = None
                    glean_data = None
                    issue_type = None
                    suggestion = None
                    triage_genie_ticket_id = None
                    ai_summary = None
                    if "issue_type" in include_set or "suggestion" in include_set:
                        if jira_tickets:
                            jira_data = fetch_jira_ticket(jira_tickets[0])
                        if exception_summary:
                            glean_data = search_glean(exception_summary)
                    if "issue_type" in include_set:
                        issue_type = classify_failure(exception_summary, exception, jira_data, glean_data)
                    if "suggestion" in include_set:
                        suggestion = generate_ai_suggestion(
                            issue_type or classify_failure(exception_summary, exception, jira_data, glean_data),
                            exception_summary, exception, jira_tickets, jira_data, glean_data
                        )
                    if "triage_genie_ticket" in include_set and testcase_id and triage_genie_session:
                        triage_genie_ticket_id = fetch_triage_genie_ticket_id(testcase_id, triage_session=triage_genie_session)
                    
                    # Generate AI Summary if requested
                    if "ai_summary" in include_set:
                        try:
                            # Fetch logs
                            logs = fetch_testcase_logs(testcase_name, test_log_url)
                            
                            # Generate AI summary
                            success, summary = generate_ai_failure_summary(
                                exception=exception,
                                exception_summary=exception_summary,
                                tester_log_url=test_log_url,
                                testcase_name=testcase_name,
                                steps_log=logs.get("steps_log", ""),
                                nutest_test_log=logs.get("nutest_test_log", "")
                            )
                            
                            if success:
                                ai_summary = summary
                            else:
                                ai_summary = f"Error generating summary: {summary}"
                                logger.warning(f"Failed to generate AI summary for {testcase_name}: {summary}")
                        except Exception as e:
                            logger.error(f"Error generating AI summary for {testcase_name}: {e}", exc_info=True)
                            ai_summary = f"Error: {str(e)}"
                    
                    # Resolve regression owner
                    regression_owner = resolve_owner(testcase_name) if testcase_name else "Unknown"
                    
                    row = {
                        "testcase_id": testcase_id,
                        "testcase_name": testcase_name,
                        "status": status,
                        "failure_stage": failure_stage,
                        "jira_tickets": jira_tickets,
                        "regression_owner": regression_owner,
                        "test_log_url": test_log_url,
                        "exception_summary": exception_summary,
                        "comments": comments,
                        "exception": exception[:200] if exception else ""
                    }
                    if intermittent_rerun is not None:
                        row["intermittent_rerun"] = intermittent_rerun
                    if issue_type is not None:
                        row["issue_type"] = issue_type
                    if suggestion is not None:
                        row["suggestion_by_ai_agent"] = suggestion
                    if triage_genie_ticket_id is not None:
                        row["triage_genie_ticket_id"] = triage_genie_ticket_id
                    if ai_summary is not None:
                        row["ai_summary"] = ai_summary
                    
                    analysis_results.append(row)
                
                logger.info(f"[END] Failed Analysis | results={len(analysis_results)} | time={time.time() - start:.2f}s")
                
                return jsonify({
                    "success": True,
                    "results": analysis_results,
                    "total_analyzed": len(analysis_results),
                    "current_branch": current_branch,
                    "tag": tag or None
                })
                
            except requests.exceptions.ConnectionError as e:
                logger.error(f"Connection error: {e}", exc_info=True)
                return jsonify({
                    "error": "Failed to connect to JITA API. Please check your network connection and ensure 'jita.eng.nutanix.com' is accessible.",
                    "details": str(e)
                }), 503
            except requests.exceptions.Timeout as e:
                logger.error(f"Timeout error: {e}", exc_info=True)
                return jsonify({
                    "error": "Request to JITA API timed out. Please try again.",
                    "details": str(e)
                }), 504
            except Exception as e:
                logger.error(f"Error fetching test results: {e}", exc_info=True)
                return jsonify({"error": f"Failed to fetch test results: {str(e)}"}), 500
        else:
            return jsonify({
                "success": True,
                "results": [],
                "message": "No task IDs found"
            })
            
    except ConnectionError as e:
        logger.error(f"Connection error: {e}", exc_info=True)
        return jsonify({
            "error": str(e),
            "type": "connection_error"
        }), 503
    except TimeoutError as e:
        logger.error(f"Timeout error: {e}", exc_info=True)
        return jsonify({
            "error": str(e),
            "type": "timeout_error"
        }), 504
    except Exception as e:
        logger.error(f"Error analyzing failed testcases: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _analyze_failed_testcases_stream(tag, task_ids, include_set):
    """Generator that yields SSE events: start, then one 'row' per result, then 'done' or 'error'."""
    try:
        tasks = fetch_regression_tasks(tag=tag, task_ids=task_ids)
        if not tasks:
            yield json.dumps({"type": "start", "total": 0, "current_branch": "", "tag": tag})
            yield json.dumps({"type": "done"})
            return
        collected_task_ids = [task["_id"]["$oid"] for task in tasks]
        all_results = fetch_test_results_batch_with_pagination(collected_task_ids)
        failed_results = [
            tr for tr in all_results
            if tr.get("status", "").lower() in ("failed", "failure")
        ]
        current_branch = (tasks[0].get("branch") or "") if tasks else ""
        triage_genie_session = create_triage_genie_session() if "triage_genie_ticket" in include_set else None

        yield json.dumps({
            "type": "start",
            "total": len(failed_results),
            "current_branch": current_branch,
            "tag": tag or None
        })

        for test_result in failed_results:
            testcase_id = None
            if isinstance(test_result.get("_id"), dict) and "$oid" in test_result.get("_id", {}):
                testcase_id = test_result["_id"]["$oid"]
            else:
                testcase_id = str(test_result.get("_id", ""))
            detailed_result = {}
            if testcase_id:
                detailed_result = fetch_detailed_test_result(testcase_id)
            test_field = test_result.get("test", {})
            if isinstance(test_field, dict):
                testcase_name = test_field.get("name", "")
            elif isinstance(test_field, str):
                testcase_name = test_field
            else:
                detailed_test = detailed_result.get("test", {})
                if isinstance(detailed_test, dict):
                    testcase_name = detailed_test.get("name", "")
                elif isinstance(detailed_test, str):
                    testcase_name = detailed_test
                else:
                    testcase_name = ""
            status = test_result.get("status", "FAILED")
            exception_summary = test_result.get("exception_summary") or detailed_result.get("exception_summary", "")
            exception = detailed_result.get("exception", "")
            jira_tickets = test_result.get("jira_tickets", [])
            test_log_url = test_result.get("test_log_url") or detailed_result.get("test_log_url", "")
            comments = test_result.get("comments") or detailed_result.get("comments") or ""
            failure_stage = determine_failure_stage({**test_result, **detailed_result})
            intermittent_rerun = is_intermittent_rerun(exception_summary) if "intermittent" in include_set else None
            jira_data = None
            glean_data = None
            issue_type = None
            suggestion = None
            triage_genie_ticket_id = None
            ai_summary = None
            if "issue_type" in include_set or "suggestion" in include_set:
                if jira_tickets:
                    jira_data = fetch_jira_ticket(jira_tickets[0])
                if exception_summary:
                    glean_data = search_glean(exception_summary)
            if "issue_type" in include_set:
                issue_type = classify_failure(exception_summary, exception, jira_data, glean_data)
            if "suggestion" in include_set:
                suggestion = generate_ai_suggestion(
                    issue_type or classify_failure(exception_summary, exception, jira_data, glean_data),
                    exception_summary, exception, jira_tickets, jira_data, glean_data
                )
            if "triage_genie_ticket" in include_set and testcase_id and triage_genie_session:
                triage_genie_ticket_id = fetch_triage_genie_ticket_id(testcase_id, triage_session=triage_genie_session)
            
            # Generate AI Summary if requested
            if "ai_summary" in include_set:
                try:
                    # Fetch logs
                    logs = fetch_testcase_logs(testcase_name, test_log_url)
                    
                    # Generate AI summary
                    success, summary = generate_ai_failure_summary(
                        exception=exception,
                        exception_summary=exception_summary,
                        tester_log_url=test_log_url,
                        testcase_name=testcase_name,
                        steps_log=logs.get("steps_log", ""),
                        nutest_test_log=logs.get("nutest_test_log", "")
                    )
                    
                    if success:
                        ai_summary = summary
                    else:
                        ai_summary = f"Error generating summary: {summary}"
                        logger.warning(f"Failed to generate AI summary for {testcase_name}: {summary}")
                except Exception as e:
                    logger.error(f"Error generating AI summary for {testcase_name}: {e}", exc_info=True)
                    ai_summary = f"Error: {str(e)}"
            
            regression_owner = resolve_owner(testcase_name) if testcase_name else "Unknown"
            row = {
                "testcase_id": testcase_id,
                "testcase_name": testcase_name,
                "status": status,
                "failure_stage": failure_stage,
                "jira_tickets": jira_tickets,
                "regression_owner": regression_owner,
                "test_log_url": test_log_url,
                "exception_summary": exception_summary,
                "comments": comments,
                "exception": exception[:200] if exception else ""
            }
            if intermittent_rerun is not None:
                row["intermittent_rerun"] = intermittent_rerun
            if issue_type is not None:
                row["issue_type"] = issue_type
            if suggestion is not None:
                row["suggestion_by_ai_agent"] = suggestion
            if triage_genie_ticket_id is not None:
                row["triage_genie_ticket_id"] = triage_genie_ticket_id
            if ai_summary is not None:
                row["ai_summary"] = ai_summary
            yield json.dumps({"type": "row", "result": row})
        yield json.dumps({"type": "done"})
    except Exception as e:
        logger.error(f"Error in analyze stream: {e}", exc_info=True)
        yield json.dumps({"type": "error", "message": str(e)})


@app.route("/mcp/regression/failed-analysis/analyze-stream", methods=["GET"])
def analyze_failed_testcases_stream():
    """Stream analysis results as Server-Sent Events so the UI can display rows as they load."""
    tag = request.args.get("tag")
    task_ids_param = request.args.get("task_ids")
    include_param = request.args.get("include", "")
    include_set = {x.strip().lower() for x in include_param.split(",") if x.strip()} if include_param else set()
    if not include_set:
        include_set = {"basic", "exception_summary", "intermittent"}
    task_ids = None
    if task_ids_param:
        task_ids = [tid.strip() for tid in task_ids_param.split(",") if tid.strip()]
    if not tag and not task_ids:
        return jsonify({"error": "Either tag or task_ids is required"}), 400

    def gen():
        for chunk in _analyze_failed_testcases_stream(tag, task_ids, include_set):
            yield f"data: {chunk}\n\n"

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/mcp/regression/failed-analysis/update-triage", methods=["PUT"])
def update_triage_comments():
    """Update comment and/or jira_ticket for an agave_test_result via JITA PUT API."""
    try:
        data = request.get_json() or {}
        test_id = data.get("test_id")
        comment = data.get("comment", "")
        jira_ticket = data.get("jira_ticket")
        if not test_id:
            return jsonify({"error": "test_id is required"}), 400
        triaged_by = os.getenv("TRIAGED_BY_USER", "sudharshan.musali")
        update_fields = {
            "comments": comment,
            "triaged_by": triaged_by
        }
        if jira_ticket is not None:
            update_fields["jira_ticket"] = jira_ticket
        payload = {
            "query": {"_id": {"$in": [{"$oid": test_id}]}},
            "data": {"$set": update_fields},
            "multi": True
        }
        url = f"{JITA_BASE}/agave_test_results"
        resp = requests.put(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            auth=JITA_AUTH,
            verify=False,
            timeout=30
        )
        if resp.status_code == 200:
            return jsonify({"success": True, "message": "Updated"})
        return jsonify({"error": resp.text or f"HTTP {resp.status_code}"}), resp.status_code if resp.status_code >= 400 else 500
    except Exception as e:
        logger.error(f"Error updating triage: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _fetch_test_result_for_task_and_name(task_id, test_name):
    """Fetch test result for a single task and test name. Returns one result row or None."""
    payload = {
        "raw_query": {"agave_task_id": {"$oid": task_id}},
        "only": "test,status,jira_tickets,comments",
        "start": 0,
        "limit": 500,
        "merge": False
    }
    try:
        resp = session.post(
            f"{JITA_BASE}/reports/agave_test_results",
            json=payload,
            timeout=60
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        results = data.get("data", [])
        for r in results:
            t = r.get("test") or {}
            name = t.get("name") if isinstance(t, dict) else (t if isinstance(t, str) else "")
            if name == test_name:
                return {
                    "status": (r.get("status") or "").lower(),
                    "jira_ticket": (r.get("jira_tickets") or [None])[0] if r.get("jira_tickets") else None,
                    "comment": r.get("comments") or None
                }
        return None
    except Exception as e:
        logger.warning(f"History fetch for task {task_id} test {test_name}: {e}")
        return None


@app.route("/mcp/regression/failed-analysis/history", methods=["GET"])
def failed_analysis_history():
    """Return past 3 runs for a test on same or other branch. For each run: status, jira_ticket or comment."""
    test_name = request.args.get("test_name")
    branch = request.args.get("branch", "")
    same_branch = request.args.get("same_branch", "true").lower() in ("1", "true", "yes")
    tag = request.args.get("tag")
    if not test_name or not tag:
        return jsonify({"error": "test_name and tag are required"}), 400
    try:
        tasks = fetch_regression_tasks(tag=tag, task_ids=None)
        if not tasks:
            return jsonify({"runs": []})
        if same_branch:
            filtered = [t for t in tasks if (t.get("branch") or "") == branch]
        else:
            filtered = [t for t in tasks if (t.get("branch") or "") != branch]
        # Sort by _id descending (newest first), take 3
        filtered.sort(key=lambda t: t.get("_id") or {}, reverse=True)
        selected = filtered[:3]
        runs = []
        for task in selected:
            task_id = task.get("_id", {}).get("$oid") if isinstance(task.get("_id"), dict) else task.get("_id")
            if not task_id:
                continue
            row = _fetch_test_result_for_task_and_name(task_id, test_name)
            if row:
                runs.append({
                    "status": "passed" if row["status"] in ("passed", "succeeded", "success") else "failed",
                    "jira_ticket": row["jira_ticket"],
                    "comment": row["comment"]
                })
            else:
                runs.append({"status": "unknown", "jira_ticket": None, "comment": None})
        return jsonify({"runs": runs})
    except Exception as e:
        logger.error(f"Error fetching history: {e}", exc_info=True)
        return jsonify({"error": str(e), "runs": []}), 500


# ======================================================
# App Runner
# ======================================================
if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5001"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "yes")
    app.run(host=host, port=port, debug=debug)
