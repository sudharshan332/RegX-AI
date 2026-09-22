"""Pure helpers for Handover: task-id parsing and sliding-history eligibility."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

_HEX_TASK_ID_RE = re.compile(r"^[a-f0-9]{20,}$", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s,]+", re.IGNORECASE)
_JIRA_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]+-\d+$")

HANDOVER_HISTORY_WINDOW = 5


class AmbiguousTestNameError(ValueError):
    """Raised when a test-name lookup matches more than one distinct full name."""

    def __init__(self, query: str, candidates: Sequence[str]):
        self.query = query or ""
        self.candidates = [c for c in (candidates or []) if c]
        preview = ", ".join(self.candidates[:8])
        extra = "" if len(self.candidates) <= 8 else ", ..."
        super().__init__(
            "Ambiguous test name %r matches %d tests: %s%s. Use a fuller name."
            % (self.query, len(self.candidates), preview, extra)
        )


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


def _is_jira_issue_key(token: str) -> bool:
    return bool(token and _JIRA_KEY_RE.match(token.strip()))


def _normalize_input_blob(text: Any) -> str:
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        chunks = [str(x) for x in text if x is not None and str(x).strip()]
        return "\n".join(chunks)
    return str(text)


def parse_handover_input(text: Any) -> Dict[str, List[str]]:
    """Parse mixed JITA URLs, hex task IDs, and testcase names.

    Task IDs come from URLs and hex tokens (comma / space / newline).
    Remaining tokens are test names split on comma / newline (dots stay intact).
    Jira keys such as ENG-123 are ignored.
    """
    blob = _normalize_input_blob(text)
    task_ids = parse_task_id_inputs(blob)
    task_id_set = set(task_ids)
    test_names: List[str] = []
    seen_names = set()

    def _add_name(name: str) -> None:
        name = (name or "").strip()
        if not name or name in seen_names:
            return
        if _HEX_TASK_ID_RE.match(name) or _is_jira_issue_key(name):
            return
        seen_names.add(name)
        test_names.append(name)

    remainder = blob
    for match in _URL_RE.finditer(blob):
        remainder = remainder.replace(match.group(0), "\n")

    for segment in re.split(r"[,\n]+", remainder):
        leftover_parts: List[str] = []
        for part in (segment or "").split():
            part = part.strip().rstrip(").,]'")
            if not part:
                continue
            if _HEX_TASK_ID_RE.match(part) or part in task_id_set:
                continue
            if _is_jira_issue_key(part):
                continue
            leftover_parts.append(part)
        if leftover_parts:
            _add_name(" ".join(leftover_parts))

    return {"task_ids": task_ids, "test_names": test_names}


def normalize_test_name_list(value: Any) -> List[str]:
    """Normalize an explicit test_names field (string or list) to unique names."""
    if value is None:
        return []
    if isinstance(value, str):
        chunks = [value]
    elif isinstance(value, (list, tuple)):
        chunks = list(value)
    else:
        chunks = [value]
    names: List[str] = []
    seen = set()
    for item in chunks:
        for name in parse_handover_input(item).get("test_names") or []:
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def get_test_name_from_run(run: Any) -> str:
    if not isinstance(run, dict):
        return ""
    test = run.get("test")
    if isinstance(test, dict):
        return (test.get("name") or "").strip()
    if isinstance(test, str):
        return test.strip()
    return (run.get("test_name") or "").strip()


def get_run_branch(run: Any) -> str:
    if not isinstance(run, dict):
        return ""
    sut = run.get("system_under_test")
    if isinstance(sut, dict):
        return (sut.get("branch") or "").strip()
    return ""


def filter_runs_for_branch(runs: Iterable[Dict[str, Any]], branch: Optional[str]) -> List[Dict[str, Any]]:
    wanted = (branch or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        run_branch = get_run_branch(run)
        # Keep rows with no branch field (trust the JITA query filter).
        if wanted and run_branch and run_branch.lower() != wanted:
            continue
        out.append(run)
    return out


def unique_test_names_from_runs(runs: Iterable[Dict[str, Any]]) -> List[str]:
    seen = set()
    names: List[str] = []
    for run in runs or []:
        name = get_test_name_from_run(run)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _run_timestamp_raw(run: Dict[str, Any]) -> Any:
    for field in ("start_time", "end_time", "updated_at", "created_at"):
        val = run.get(field)
        if val not in (None, ""):
            return val
    return ""


def run_timestamp_key(run: Optional[Dict[str, Any]]) -> str:
    """Comparable timestamp string (ISO / numeric) for newest-first sorting."""
    if not isinstance(run, dict):
        return ""
    raw = _run_timestamp_raw(run)
    while isinstance(raw, dict):
        raw = raw.get("$date") or raw.get("$numberLong") or raw.get("$numberInt") or ""
    return str(raw) if raw not in (None, "") else ""


def select_newest_runs(
    runs: Iterable[Dict[str, Any]],
    limit: int = HANDOVER_HISTORY_WINDOW,
) -> List[Dict[str, Any]]:
    """Return up to ``limit`` runs, newest-first by timestamp."""
    items = [r for r in (runs or []) if isinstance(r, dict)]
    items.sort(key=run_timestamp_key, reverse=True)
    if limit is None or limit < 0:
        return items
    return items[:limit]


def pick_runs_for_test_query(
    query: str,
    runs: Iterable[Dict[str, Any]],
) -> Tuple[Optional[str], List[Dict[str, Any]], List[str]]:
    """Resolve a user test-name query against fetched runs.

    Preference: exact name, then unique dotted suffix, then unique substring.
    Returns (resolved_name, matching_runs, ambiguous_candidates).
    """
    query = (query or "").strip()
    items = [r for r in (runs or []) if isinstance(r, dict)]
    if not query:
        return None, [], []

    exact = [r for r in items if get_test_name_from_run(r) == query]
    if exact:
        return query, exact, []

    q_lower = query.lower()
    names = unique_test_names_from_runs(items)

    suffix = [
        n for n in names
        if n.lower() == q_lower or n.lower().endswith("." + q_lower)
    ]
    if len(suffix) == 1:
        name = suffix[0]
        return name, [r for r in items if get_test_name_from_run(r) == name], []
    if len(suffix) > 1:
        return None, [], suffix

    substring = [n for n in names if q_lower in n.lower()]
    if len(substring) == 1:
        name = substring[0]
        return name, [r for r in items if get_test_name_from_run(r) == name], []
    if len(substring) > 1:
        return None, [], substring

    return query, [], []


def parse_record_search_queries(value: Any) -> List[str]:
    """Normalize q / queries / test_names into unique non-empty query strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        chunks = [str(x) for x in value if x is not None and str(x).strip()]
    else:
        chunks = [str(value)]
    out: List[str] = []
    seen = set()
    for chunk in chunks:
        for token in re.split(r"[\s,\n\r]+", chunk):
            token = (token or "").strip()
            if not token:
                continue
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(token)
    return out


def filter_records_by_query(
    records: Iterable[Dict[str, Any]],
    queries: Optional[Sequence[str]] = None,
    date_field: str = "handover_date",
) -> List[Dict[str, Any]]:
    """Filter records by test_name substring. Empty queries return all, newest-first."""
    items = [r for r in (records or []) if isinstance(r, dict)]
    q_lowers = [str(q).strip().lower() for q in (queries or []) if str(q).strip()]
    if q_lowers:
        items = [
            r for r in items
            if any(q in (r.get("test_name") or "").lower() for q in q_lowers)
        ]
    seen = set()
    unique: List[Dict[str, Any]] = []
    for r in items:
        key = (
            (r.get("test_name") or "").strip(),
            (r.get(date_field) or "").strip(),
            (r.get("lst_file") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    unique.sort(key=lambda r: r.get(date_field) or "", reverse=True)
    return unique


def record_matches_delete_key(
    record: Optional[Dict[str, Any]],
    test_name: str,
    date_value: str,
    lst_file: str,
    date_field: str,
) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        (record.get("test_name") or "").strip() == (test_name or "").strip()
        and (record.get(date_field) or "").strip() == (date_value or "").strip()
        and (record.get("lst_file") or "").strip() == (lst_file or "").strip()
    )


def delete_record_from_list(
    records: Iterable[Dict[str, Any]],
    test_name: str,
    date_value: str,
    lst_file: str,
    date_field: str,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Return (remaining records, whether a row was removed). First match only."""
    items = [r for r in (records or []) if isinstance(r, dict)]
    for i, r in enumerate(items):
        if record_matches_delete_key(r, test_name, date_value, lst_file, date_field):
            items.pop(i)
            return items, True
    return items, False


def find_record_in_list(
    records: Iterable[Dict[str, Any]],
    test_name: str,
    date_value: str,
    lst_file: str,
    date_field: str,
) -> Optional[Dict[str, Any]]:
    """First record matching the delete key, or None."""
    for r in records or []:
        if record_matches_delete_key(r, test_name, date_value, lst_file, date_field):
            return r
    return None


# Named record-delete admins (usernames and emails). JP_DELETE_ADMIN_USERS is
# unioned in by the Flask layer.
DEFAULT_RECORD_ADMIN_USERS = {
    "swapnil.wankhede",
    "swapnil.wankhede@nutanix.com",
    "sudharshan.musali",
    "sudharshan.musali@nutanix.com",
}

_UNKNOWN_CREATORS = {"", "unknown", "n/a", "-", "none"}
_CORP_EMAIL_DOMAIN = "nutanix.com"


def identity_keys(*values: Any) -> set:
    """Lowercased aliases: raw value, local-part, and local-part@nutanix.com."""
    keys = set()
    for raw in values:
        if raw is None:
            continue
        if isinstance(raw, (list, tuple, set)):
            keys.update(identity_keys(*raw))
            continue
        text = str(raw).strip().lower()
        if not text or text in _UNKNOWN_CREATORS:
            continue
        keys.add(text)
        local = text.split("@")[0].strip()
        if local and local not in _UNKNOWN_CREATORS:
            keys.add(local)
            keys.add("%s@%s" % (local, _CORP_EMAIL_DOMAIN))
    return keys


def is_unknown_creator(by_whom: Any) -> bool:
    return str(by_whom or "").strip().lower() in _UNKNOWN_CREATORS


def is_record_admin(username: Any, email: Any, extra_admins: Optional[Iterable[Any]] = None) -> bool:
    actor = identity_keys(username, email)
    admins = identity_keys(*DEFAULT_RECORD_ADMIN_USERS, *(extra_admins or []))
    return bool(actor and actor & admins)


def can_delete_record(
    record: Optional[Dict[str, Any]],
    username: Any,
    email: Any,
    extra_admins: Optional[Iterable[Any]] = None,
) -> bool:
    """True if the actor is a record admin or the creator of this row."""
    if is_record_admin(username, email, extra_admins):
        return True
    if not isinstance(record, dict):
        return False
    by_whom = record.get("by_whom")
    if is_unknown_creator(by_whom):
        return False
    return bool(identity_keys(by_whom) & identity_keys(username, email))


def empty_handover_test_case(test_name: str) -> Dict[str, Any]:
    return {
        "test_name": test_name,
        "status": "Failed",
        "total_count": 0,
        "passed_count": 0,
        "jira_tickets": [],
        "exception_summary": None,
        "test_log_url": None,
        "failure_analysis": None,
        "bug_type": None,
        "eligibility_reason": None,
    }


def sorted_task_ids_from_runs(runs: Iterable[Dict[str, Any]]) -> List[str]:
    """Newest-first unique task IDs taken from run rows."""
    pairs: List[Tuple[str, str]] = []
    seen = set()
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        tid = get_task_id_from_run(run)
        if not tid:
            oid = run.get("_id")
            if isinstance(oid, dict):
                tid = oid.get("$oid")
            elif oid:
                tid = str(oid)
        if not tid or tid in seen:
            continue
        seen.add(tid)
        pairs.append((tid, run_timestamp_key(run)))
    pairs.sort(key=lambda item: item[1], reverse=True)
    return [tid for tid, _ in pairs]


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
    """Extract task_id string from a test run's agave_task_id (or result _id)."""
    if not isinstance(run, dict):
        return None
    aid = run.get("agave_task_id")
    if isinstance(aid, dict) and "$oid" in aid:
        return aid["$oid"]
    if aid:
        return str(aid)
    oid = run.get("_id")
    if isinstance(oid, dict) and "$oid" in oid:
        return oid["$oid"]
    if oid:
        return str(oid)
    return None


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
