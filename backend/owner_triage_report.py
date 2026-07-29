"""
Notebook-aligned owner triage aggregation (Execution_Status_Latest Report 2).

Strict row schema for the dashboard table:
  Regression_owner | Total | Total untriaged | Failed | Skipped | Warning | Killed
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

UNTRIAGED_STATUSES = ("Failed", "Skipped", "Warning", "Killed")
PASSED_COMMENT_RE = re.compile(r"\{\s*Test\s*Passed", re.IGNORECASE)
TASK_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def normalize_task_ids(task_ids: Any) -> Tuple[List[str], List[str]]:
    """
    Normalize + validate JITA task OIDs.

    Returns (valid_ids_deduped_order_preserved, invalid_raw_values).
    """
    if task_ids is None:
        return [], []

    raw_parts: List[str] = []
    if isinstance(task_ids, str):
        raw_parts = [p for p in re.split(r"[\s,]+", task_ids.strip()) if p]
    elif isinstance(task_ids, (list, tuple)):
        for item in task_ids:
            if item is None:
                continue
            if isinstance(item, str) and ("," in item or " " in item.strip()):
                raw_parts.extend(p for p in re.split(r"[\s,]+", item.strip()) if p)
            else:
                s = str(item).strip()
                if s:
                    raw_parts.append(s)
    else:
        s = str(task_ids).strip()
        if s:
            raw_parts.append(s)

    valid: List[str] = []
    invalid: List[str] = []
    seen = set()
    for part in raw_parts:
        if not TASK_ID_RE.match(part):
            invalid.append(part)
            continue
        # Lowercase so AAA... and aaa... do not double-count / false-dupe
        part = part.lower()
        if part in seen:
            continue
        seen.add(part)
        valid.append(part)
    return valid, invalid


def extract_task_ids_from_execution_url(execution_url: str) -> List[str]:
    """Extract task IDs from a JITA results URL."""
    if not execution_url or not str(execution_url).strip():
        return []
    url = str(execution_url).strip()
    parsed = urlparse(url)
    if "/agave_tasks/" in parsed.path:
        task_id = parsed.path.rstrip("/").split("/")[-1]
        valid, _ = normalize_task_ids([task_id])
        return valid
    qs = parse_qs(parsed.query)
    raw_list = qs.get("task_ids") or []
    if not raw_list:
        return []
    raw = raw_list[0] if isinstance(raw_list[0], str) else ",".join(raw_list)
    valid, _ = normalize_task_ids(raw)
    return valid


def _test_name(record: dict) -> str:
    test = record.get("test")
    if isinstance(test, dict):
        return (test.get("name") or "").strip()
    return (record.get("name") or "").strip()


def _jira_tickets_str(record: dict) -> str:
    tickets = record.get("jira_tickets") or []
    if isinstance(tickets, str):
        return tickets.strip()
    if isinstance(tickets, list):
        return ",".join(str(t).strip() for t in tickets if t).strip()
    return ""


def _comment_str(record: dict) -> str:
    return str(record.get("comments") or record.get("comment") or "")


def is_untriaged(record: dict) -> bool:
    """Notebook rule: bad status, no jira, not '{Test Passed' comment."""
    status = record.get("status") or ""
    if status not in UNTRIAGED_STATUSES:
        return False
    if _jira_tickets_str(record):
        return False
    if PASSED_COMMENT_RE.search(_comment_str(record)):
        return False
    return True


def build_owner_status_table(
    test_records: Sequence[dict],
    resolve_owner: Callable[[str], str],
) -> Dict[str, Any]:
    """
    Aggregate notebook Report 2 rows.

    Returns:
      {
        "rows": [ {Regression_owner, Total, Total untriaged, Failed, Skipped, Warning, Killed}, ... ],
        "unmapped_tests": [...],
        "meta": {...}
      }
    """
    by_name: Dict[str, dict] = {}
    for rec in test_records:
        name = _test_name(rec)
        if not name or name in by_name:
            continue
        by_name[name] = rec

    owner_status = defaultdict(lambda: {s: 0 for s in UNTRIAGED_STATUSES})
    owner_total_bad = defaultdict(int)
    unmapped_tests: List[str] = []

    for name, rec in by_name.items():
        owner = resolve_owner(name) or "Unmapped"
        status = rec.get("status") or ""
        if status in UNTRIAGED_STATUSES:
            owner_total_bad[owner] += 1
        if is_untriaged(rec):
            owner_status[owner][status] += 1
            if owner == "Unmapped":
                unmapped_tests.append(name)

    owners = sorted(set(owner_status.keys()) | set(owner_total_bad.keys()))
    rows: List[Dict[str, Any]] = []
    for owner in owners:
        status_counts = owner_status[owner]
        total_untriaged = sum(status_counts[s] for s in UNTRIAGED_STATUSES)
        rows.append({
            "Regression_owner": owner,
            "Total": int(owner_total_bad[owner]),
            "Total untriaged": int(total_untriaged),
            "Failed": int(status_counts["Failed"]),
            "Skipped": int(status_counts["Skipped"]),
            "Warning": int(status_counts["Warning"]),
            "Killed": int(status_counts["Killed"]),
        })

    rows.sort(key=lambda r: (-r["Total untriaged"], r["Regression_owner"]))

    total_bad = sum(r["Total"] for r in rows)
    total_untriaged = sum(r["Total untriaged"] for r in rows)

    return {
        "rows": rows,
        "unmapped_tests": unmapped_tests,
        "meta": {
            "unique_tests": len(by_name),
            "total": total_bad,
            "total_untriaged": total_untriaged,
        },
    }


def resolve_task_ids_from_payload(
    *,
    task_ids: Any = None,
    execution_url: Optional[str] = None,
) -> Tuple[List[str], List[str], Optional[str], str]:
    """
    Resolve task IDs for the report.

    Returns (valid_ids, invalid_ids, error_message, source).
    """
    if task_ids is not None and task_ids != "" and task_ids != []:
        valid, invalid = normalize_task_ids(task_ids)
        if not valid and invalid:
            return [], invalid, "No valid JITA task IDs (expected 24-char hex)", "task_ids"
        if not valid:
            return [], [], "task_ids is empty", "task_ids"
        return valid, invalid, None, "task_ids"

    if execution_url:
        valid = extract_task_ids_from_execution_url(execution_url)
        if not valid:
            return [], [], "execution_url did not contain valid task_ids", "execution_url"
        return valid, [], None, "execution_url"

    return [], [], "Provide task_ids (array of JITA OIDs) or execution_url", "none"
