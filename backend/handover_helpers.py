"""Pure helpers for Handover: task-id parsing and sliding-history eligibility."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

_HEX_TASK_ID_RE = re.compile(r"^[a-f0-9]{20,}$", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s,]+", re.IGNORECASE)


def parse_jita_url(url: str) -> List[str]:
    """Extract task_ids from a JITA results URL or /agave_tasks/<id> path."""
    if not url or not str(url).strip():
        return []
    text = str(url).strip()
    parsed = urlparse(text)
    if "/agave_tasks/" in parsed.path:
        task_id = parsed.path.rstrip("/").split("/")[-1]
        if task_id and len(task_id) >= 20:
            return [task_id]
    qs = parse_qs(parsed.query)
    task_ids_param = qs.get("task_ids", [])
    if not task_ids_param:
        return []
    raw = task_ids_param[0] if isinstance(task_ids_param[0], str) else ",".join(task_ids_param)
    return [tid.strip() for tid in raw.split(",") if tid.strip()]


def parse_task_id_inputs(text: Any) -> List[str]:
    """Parse mixed JITA URLs and/or hex task IDs (comma / space / newline separated).

    1. Extract all http(s) URLs and pull task ids via parse_jita_url
    2. Strip those URLs from the text
    3. Split remainder on commas/whitespace and keep hex task ids
    4. Dedupe preserving order
    """
    if text is None:
        return []
    if isinstance(text, (list, tuple)):
        chunks = [str(x) for x in text if x is not None and str(x).strip()]
        blob = "\n".join(chunks)
    else:
        blob = str(text)
    if not blob.strip():
        return []

    found: List[str] = []
    seen = set()

    def _add(tid: str) -> None:
        tid = (tid or "").strip()
        if not tid or tid in seen:
            return
        seen.add(tid)
        found.append(tid)

    remainder = blob
    for match in _URL_RE.finditer(blob):
        url = match.group(0).rstrip(").,]'")
        for tid in parse_jita_url(url):
            _add(tid)
        remainder = remainder.replace(match.group(0), " ")

    for token in re.split(r"[,\s]+", remainder):
        token = (token or "").strip()
        if token and _HEX_TASK_ID_RE.match(token):
            _add(token)

    return found


def is_intransit_lst_path(path: Optional[str]) -> bool:
    return "intransit" in (path or "").lower()


def prefer_non_intransit_lst(ranked_paths: Sequence[str]) -> str:
    """Return first non-intransit path from a ranked list (or empty string)."""
    for path in ranked_paths or []:
        p = (path or "").strip()
        if p and not is_intransit_lst_path(p):
            return p
    return ""


def categorize_bug_type_from_issuetype(issuetype: Optional[str]) -> Optional[str]:
    """Categorize bug type from a Jira issuetype name."""
    if not issuetype:
        return None
    issuetype_lower = str(issuetype).lower()
    if "environment" in issuetype_lower:
        return "Environment"
    if "flaky" in issuetype_lower:
        return "Flaky"
    if "test" in issuetype_lower or "testbed" in issuetype_lower:
        return "Test Bug"
    if "bug" in issuetype_lower:
        return "Product Bug"
    return None


def _normalize_run_bug_types(
    tickets: Sequence[str],
    ticket_bug_types: Optional[Dict[str, Optional[str]]] = None,
    resolve_issuetype: Optional[Callable[[str], Optional[str]]] = None,
) -> List[str]:
    """Resolve bug types for tickets on a single failed run."""
    types: List[str] = []
    seen = set()
    ticket_bug_types = ticket_bug_types or {}
    for raw in tickets or []:
        ticket = (raw or "").strip()
        if not ticket:
            continue
        key = ticket.upper()
        bug_type = ticket_bug_types.get(key) or ticket_bug_types.get(ticket)
        if bug_type is None and resolve_issuetype is not None:
            issuetype = resolve_issuetype(ticket)
            bug_type = categorize_bug_type_from_issuetype(issuetype)
        if bug_type and bug_type not in seen:
            seen.add(bug_type)
            types.append(bug_type)
    return types


def is_product_bug_only_failure(bug_types: Sequence[Optional[str]]) -> bool:
    """True when there is at least one Product Bug and no blocking types."""
    cleaned = [bt for bt in (bug_types or []) if bt]
    if not cleaned:
        return False
    if any(bt in ("Test Bug", "Environment", "Flaky") for bt in cleaned):
        return False
    return all(bt == "Product Bug" for bt in cleaned)


def evaluate_sliding_eligibility(
    ordered_runs: Sequence[Dict[str, Any]],
    ticket_bug_types: Optional[Dict[str, Optional[str]]] = None,
    resolve_issuetype: Optional[Callable[[str], Optional[str]]] = None,
) -> Tuple[bool, Optional[str], int]:
    """Evaluate handover eligibility for one testcase across ordered runs.

    ``ordered_runs`` must be newest-first. Each item:
      {"status": "Succeeded"|..., "jira_tickets": [...], "bug_types": [...]?}

    Eligible if two Succeeded anchors exist with only Product-Bug-only failures between them.

    Returns (eligible, reason, passed_count) where reason is
    ``consecutive_pass``, ``product_bug_gap``, or None.
    """
    seq: List[Dict[str, Any]] = []
    for run in ordered_runs or []:
        if not isinstance(run, dict):
            continue
        status = (run.get("status") or "").strip()
        if not status:
            continue
        # Skip non-terminal noise for the sliding window
        if status in ("Pending", "Running", "Skipped"):
            continue
        tickets = run.get("jira_tickets") or []
        bug_types = run.get("bug_types")
        if bug_types is None:
            bug_types = _normalize_run_bug_types(tickets, ticket_bug_types, resolve_issuetype)
        seq.append({"status": status, "bug_types": list(bug_types or [])})

    passed_count = sum(1 for r in seq if r["status"] == "Succeeded")
    n = len(seq)
    if n < 2:
        return False, None, passed_count

    for i in range(n):
        if seq[i]["status"] != "Succeeded":
            continue
        for j in range(i + 1, n):
            if seq[j]["status"] != "Succeeded":
                # Gap entries must be Product-Bug-only failures; anything else breaks the window.
                if not is_product_bug_only_failure(seq[j]["bug_types"]):
                    break
                continue
            gap = seq[i + 1 : j]
            if not gap:
                return True, "consecutive_pass", passed_count
            if all(is_product_bug_only_failure(r["bug_types"]) for r in gap):
                return True, "product_bug_gap", passed_count
            break
    return False, None, passed_count


def get_task_id_from_run(run: Dict[str, Any]) -> Optional[str]:
    """Extract task_id string from a test run's agave_task_id."""
    if not isinstance(run, dict):
        return None
    aid = run.get("agave_task_id")
    if not aid:
        return None
    if isinstance(aid, dict) and "$oid" in aid:
        return aid["$oid"]
    return str(aid)


def order_runs_for_test(
    runs: Iterable[Dict[str, Any]],
    sorted_task_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    """Order a test's runs to match sorted_task_ids (newest-first), skipping missing tasks."""
    by_tid: Dict[str, Dict[str, Any]] = {}
    for run in runs or []:
        tid = get_task_id_from_run(run)
        if tid and tid not in by_tid:
            by_tid[tid] = run
    ordered = []
    for tid in sorted_task_ids:
        if tid in by_tid:
            ordered.append(by_tid[tid])
    return ordered
