"""CDP release status for one milestone.

Feat rows come from the TCMS milestone aggregate. Feat folders are the
directories directly under the Sourcegraph tree for that release. A sibling
whose name starts with REGRESSION is the handover folder, not a feat.
intransit paths do not count.

The summary view reads the same aggregate with the TCMS milestone filters
release managers use (All, Feat, Regression) and compares that set with
JITA tester tags stored for the milestone.
"""
import json
import logging
import os
import re
from datetime import datetime
from urllib.parse import quote

import requests
from flask import jsonify, request

logger = logging.getLogger(__name__)

TCMS_BASE = os.getenv("TCMS_BASE", "https://tcms.eng.nutanix.com/api-readonly/v1").rstrip("/")
TCMS_SUMMARY_BASE = os.getenv("TCMS_SUMMARY_BASE", "https://tcms.eng.nutanix.com/api/v1").rstrip("/")
TCMS_USER = os.getenv("TCMS_USER", "agave_bot")
TCMS_PASSWORD = os.getenv("TCMS_PASSWORD", "admin")
TCMS_UI = "https://tcms.eng.nutanix.com/#/testcases/milestone/"

_MILESTONE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_REPO = "nugerrit.ntnxdpro.com/nutest-py3-tests"
_SG = "https://sourcegraph.ntnxdpro.com"

# First folder under each root is a feat. A REGRESSION folder under that root
# is the handover set for the same release.
RELEASES = {
    "7.7": {
        "root": "test_sets/milestones/7.7/CDP/FunctionalTest",
        "branch": "ganges-7.7-stable",
    },
    "7.6": {
        "root": "test_sets/milestones/7.6/CDP",
        "branch": "ganges-7.6-stable",
    },
}
_ROOT_RE = re.compile(r"^test_sets/milestones/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")
_PASS = {"succeeded", "passed", "success", "pass"}
_FAIL = {"failed", "failure", "fail", "error"}
_PAGE_SIZE = 500
_MAX_PAGES = 20
_TEAM = "CDP"
_EXCLUDED_TAGS = ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]
_VIEW_TYPES = ("all", "feat", "regression")
_VIEW_LABEL = {"all": "All", "feat": "Feat", "regression": "Regression"}
_TAG_PRESETS = ("Full regression", "Upgrade", "External storage")
_TAG_NAME_RE = re.compile(r"^[\w.\-|/: ]{1,200}$")
_MAX_TAGS = 20
_LIST_LIMIT = 300
_BULK_MIN = 5
_TOP_QI = 5
_RESULT_RANK = {"pass": 2, "fail": 1, "other": 0}
_JIRA_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+", re.I)
_BUG_TYPES = "product,test,framework,infra,other"

# Filled by register_routes from the already-loaded Flask module.
_fetch_tasks = None
_fetch_results = None
_qi_impact = None


class DashboardError(Exception):
    pass


def _blank_status(status):
    return (status or "").strip().lower() in ("", "not run", "not_run")


def _result_kind(status):
    value = (status or "").strip().lower()
    if value in _PASS:
        return "pass"
    if value in _FAIL:
        return "fail"
    return "other"


def _ticket_ids(raw):
    ids = []
    for item in raw or []:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(
                item.get("id")
                or item.get("key")
                or item.get("name")
                or item.get("ticket")
                or ""
            ).strip()
        else:
            text = ""
        if text and text not in ids:
            ids.append(text)
    return ids


def _owners(raw):
    names = []
    for item in raw or []:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("name") or item.get("email") or "").strip()
        else:
            text = ""
        if text and text not in names:
            names.append(text)
    return names


def _paths(test_sets):
    paths = []
    for item in test_sets or []:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("path") or item.get("name") or "").strip()
        else:
            text = ""
        if text:
            paths.append(text.replace("\\", "/"))
    return paths


def nutest_branch_for(nos):
    """Map a NOS version to the nutest branch that holds its feat tree.

    master stays on master. 7.6.1 and 7.5.1 use the train branch
    ganges-7.6-stable and ganges-7.5-stable. Any longer version uses
    ganges-<major>.<minor>-stable.
    """
    text = (nos or "").strip()
    low = text.lower()
    if low in ("master", "main"):
        return {"milestone": "master", "branch": "master"}
    match = re.match(r"^ganges-(\d+\.\d+(?:\.\d+)*)-stable$", low)
    version = match.group(1) if match else text
    parts = version.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts):
        return None
    train = "%s.%s" % (parts[0], parts[1])
    return {"milestone": version, "branch": "ganges-%s-stable" % train}


def _safe_root(root):
    root = (root or "").strip().strip("/")
    if ".." in root or not _ROOT_RE.match(root):
        return ""
    return root


def release_info(milestone, root=None, branch=None):
    cfg = RELEASES.get(milestone)
    if cfg and not root:
        root = cfg["root"]
        branch = cfg["branch"]
    root = _safe_root(root)
    if not root:
        return None
    if not branch:
        mapped = nutest_branch_for(milestone)
        branch = mapped["branch"] if mapped else ""
    if not branch:
        return None
    return {
        "milestone": milestone,
        "root": root,
        "branch": branch,
        "sourcegraph": "%s/%s@%s/-/tree/%s" % (_SG, _REPO, branch, root),
    }


def classify_path(path, milestone, root=None):
    """Return (feat_name or '', in_regression) for one test-set path.

    Feats are the directories under <root>/FEATS/, one row per directory.
    Nested folders stay separate (FEAT-19686/FEAT-17396 is not FEAT-19686).
    <root>/REGRESSION/ is the handover set and is not a feat row.
    """
    info = release_info(milestone, root=root)
    if not info:
        return "", False
    lowered = path.lower()
    if "intransit" in lowered:
        return "", False
    root = info["root"].lower().rstrip("/") + "/"
    idx = lowered.find(root)
    if idx < 0:
        return "", False
    parts = [part for part in path[idx + len(root):].split("/") if part]
    if not parts:
        return "", False
    head = parts[0].lower()
    if head == "regression" or head.startswith("regression"):
        return "", True
    if head != "feats":
        return "", False
    feat_parts = parts[1:]
    if feat_parts and feat_parts[-1].lower().endswith(".lst"):
        feat_parts = feat_parts[:-1]
    if not feat_parts:
        return "", False
    return "/".join(feat_parts), False


def _pass_number(name):
    match = re.search(r"(\d+)\s*$", name or "")
    return int(match.group(1)) if match else -1


def _run_time(run):
    value = run.get("end_time") or run.get("start_time")
    if isinstance(value, dict):
        value = value.get("$date")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _branch_run(item):
    """Latest run recorded on this milestone, not a carried-over overall.

    RC1/RC2/RC3 are the runs on this release. overall can say succeeded
    when none of those passes actually ran.
    """
    last_result = item.get("last_result")
    if not isinstance(last_result, list):
        return {}
    overall = None
    ran = []
    has_branch_pass = False
    for entry in last_result:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("pass_name") or "").strip()
        run = entry.get("run") if isinstance(entry.get("run"), dict) else {}
        if name.lower() == "overall":
            overall = run
            continue
        if not name:
            continue
        has_branch_pass = True
        if str(run.get("status") or "").strip():
            ran.append((_run_time(run), _pass_number(name), run))
    if has_branch_pass:
        if not ran:
            return {}
        ran.sort()
        return ran[-1][2]
    return overall if isinstance(overall, dict) else {}


def parse_row(item, milestone, root=None):
    if not isinstance(item, dict):
        return None
    tc = item.get("test_case") if isinstance(item.get("test_case"), dict) else {}
    name = str(item.get("name") or tc.get("name") or "").strip()
    if not name:
        return None
    feats = {}
    in_regression = False
    for path in _paths(tc.get("test_sets")):
        feat, is_reg = classify_path(path, milestone, root=root)
        if feat:
            feats[feat.lower()] = feat
        if is_reg:
            in_regression = True
    if not feats and not in_regression:
        return None
    run = _branch_run(item)
    tickets = _ticket_ids(run.get("tickets"))
    status = str(run.get("status") or "").strip() or "Not run"
    return {
        "name": name,
        "in_regression": in_regression,
        "status": status,
        "issue_type": str(run.get("issue_type") or "").strip(),
        "tickets": tickets,
        "owners": _owners(tc.get("owners")),
        "feats": feats,
        "target_branch": str(item.get("target_branch") or "").strip(),
    }


def _merge_test(existing, incoming):
    existing["in_regression"] = existing["in_regression"] or incoming["in_regression"]
    if _blank_status(existing["status"]) and not _blank_status(incoming["status"]):
        existing["status"] = incoming["status"]
        existing["issue_type"] = incoming["issue_type"]
        existing["tickets"] = incoming["tickets"]
    if not existing["owners"] and incoming["owners"]:
        existing["owners"] = incoming["owners"]
    if incoming.get("target_branch") and not existing.get("target_branch"):
        existing["target_branch"] = incoming["target_branch"]
    for key, display in incoming["feats"].items():
        existing["feats"].setdefault(key, display)


def _color(tests):
    total = len(tests)
    handed = sum(1 for test in tests if test["in_regression"])
    passed = sum(1 for test in tests if test["result"] == "pass")
    failed = sum(1 for test in tests if test["result"] == "fail")
    not_run = total - passed - failed
    if handed < total:
        return "black", None, handed, passed, failed, not_run
    if not_run:
        return "not_run", None, handed, passed, failed, not_run
    if failed == 0:
        return "green", 100, handed, passed, failed, not_run
    rate = (100.0 * passed) / (passed + failed)
    color = "yellow" if rate > 80 else "red"
    return color, round(rate), handed, passed, failed, not_run


def _branch_matches_release(target_branch, release_branch, milestone):
    """True when this row's branch is the selected release, including its -pc build."""
    branch = (target_branch or "").strip().lower()
    release = (release_branch or "").strip().lower()
    if not branch:
        return False
    if release and (branch == release or branch.startswith(release + "-")):
        return True
    version = (milestone or "").strip().lower()
    if not version:
        return False
    return re.search(r"(?<![\d.])" + re.escape(version) + r"(?![\d.])", branch) is not None


def build_dashboard(rows, milestone, root=None, branch=None):
    info = release_info(milestone, root=root, branch=branch)
    if not info:
        return {"milestone": milestone, "feat_count": 0, "summary": {}, "feats": []}
    by_name = {}
    for item in rows or []:
        parsed = parse_row(item, milestone, root=info["root"])
        if parsed is None:
            continue
        key = parsed["name"].lower()
        current = by_name.get(key)
        if current is None:
            parsed["name_key"] = key
            by_name[key] = parsed
        else:
            _merge_test(current, parsed)

    for record in by_name.values():
        target = record.get("target_branch") or ""
        if target and not _branch_matches_release(target, info["branch"], info["milestone"]):
            record["status"] = "Not run"
            record["issue_type"] = ""
            record["tickets"] = []

    feat_tests = {}
    for record in by_name.values():
        record["result"] = _result_kind(record["status"])
        for feat_key, display in record["feats"].items():
            bucket = feat_tests.setdefault(feat_key, {"name": display, "tests": []})
            bucket["tests"].append(record)

    feats = []
    for bucket in feat_tests.values():
        ordered = sorted(
            bucket["tests"],
            key=lambda test: (
                0 if test["result"] == "fail" else 1 if not test["in_regression"] else 2,
                test["name"].lower(),
            ),
        )
        color, pass_rate, handed, passed, failed, not_run = _color(ordered)
        feats.append({
            "name": bucket["name"],
            "color": color,
            "total": len(ordered),
            "handed_over": handed,
            "passed": passed,
            "failed": failed,
            "not_run": not_run,
            "pass_rate": pass_rate,
            "tests": [
                {
                    "name": test["name"],
                    "in_regression": test["in_regression"],
                    "status": test["status"],
                    "issue_type": test["issue_type"],
                    "tickets": test["tickets"],
                    "owners": test["owners"],
                }
                for test in ordered
            ],
        })
    feats.sort(key=lambda feat: feat["name"].lower())
    summary = {"black": 0, "red": 0, "yellow": 0, "green": 0, "not_run": 0}
    for feat in feats:
        summary[feat["color"]] = summary.get(feat["color"], 0) + 1
    info.update({"feat_count": len(feats), "summary": summary, "feats": feats})
    return info


def fetch_milestone_rows(milestone, root=None, branch=None):
    info = release_info(milestone, root=root, branch=branch)
    if not info:
        raise DashboardError("Unsupported release")
    root = re.escape(info["root"])
    match = {
        "$and": [
            {"target_milestone": milestone},
            {"deleted": False},
            {"test_case.deprecated": False},
            {"test_case.test_sets": {"$regex": root + "/(FEATS|REGRESSION)/", "$options": "i"}},
        ]
    }
    rows = []
    for page in range(_MAX_PAGES):
        payload = [
            {"$match": match},
            {"$project": {
                "name": 1,
                "tickets": 1,
                "test_case.name": 1,
                "test_case.test_sets": 1,
                "test_case.owners": 1,
                "target_branch": 1,
                "last_result": 1,
            }},
            {"$skip": page * _PAGE_SIZE},
            {"$limit": _PAGE_SIZE},
        ]
        try:
            response = requests.post(
                "%s/milestone_all_test_cases/aggregate" % TCMS_BASE,
                json=payload,
                auth=(TCMS_USER, TCMS_PASSWORD),
                headers={"Content-Type": "application/json"},
                verify=False,
                timeout=120,
            )
        except requests.RequestException as exc:
            logger.warning("TCMS release dashboard request failed: %s", exc)
            raise DashboardError("TCMS request failed")
        if response.status_code != 200:
            logger.warning("TCMS release dashboard HTTP %s", response.status_code)
            raise DashboardError("TCMS returned HTTP %s" % response.status_code)
        try:
            body = response.json()
        except ValueError:
            raise DashboardError("TCMS returned a non-JSON response")
        batch = body.get("data") if isinstance(body, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
    return rows


def lookup_release(nos):
    """7.6.1 uses ganges-7.6-stable. 7.5.1 uses ganges-7.5-stable."""
    mapped = nutest_branch_for(nos)
    if not mapped:
        raise DashboardError("Enter a NOS version such as 7.5.1")
    milestone = mapped["milestone"]
    if milestone in RELEASES:
        return release_info(milestone)
    return release_info(
        milestone,
        root="test_sets/milestones/%s/CDP" % milestone,
        branch=mapped["branch"],
    )


def view_type(raw):
    value = (raw or "all").strip().lower()
    if value not in _VIEW_TYPES:
        raise DashboardError("Unsupported type")
    return value


def summary_match(milestone, raw_type):
    """Mongo match for the TCMS milestone page filters.

    All is the milestone CDP test-set scope. Feat keeps rows whose release
    equals the milestone. Regression keeps every other release. Feat and
    Regression also drop longevity and limited-run tags. Deleted and
    deprecated rows are left out, matching the other TCMS reads in RegX.
    """
    kind = view_type(raw_type)
    text = (milestone or "").strip()
    if not _MILESTONE_RE.match(text):
        raise DashboardError("Unsupported release")
    broad = "test_sets/milestones/%s/" % text
    team_path = "test_sets/milestones/%s/%s/" % (text, _TEAM)
    clauses = [
        {"target_milestone": text},
        {"deleted": False},
        {"test_case.deprecated": False},
        {"test_case.test_sets": {"$regex": re.escape(broad), "$options": "i"}},
        {"additional_data.team": "%s/%s" % (text, _TEAM)},
        {"test_case.test_sets": {"$regex": re.escape(team_path), "$options": "i"}},
    ]
    if kind == "feat":
        clauses.append({"release_name": text})
        clauses.append({"test_case.metadata.tags": {"$nin": list(_EXCLUDED_TAGS)}})
    elif kind == "regression":
        clauses.append({"release_name": {"$ne": text}})
        clauses.append({"test_case.metadata.tags": {"$nin": list(_EXCLUDED_TAGS)}})
    return {"$and": clauses}


def _tcms_filters(text, kind):
    filters = [
        {"field": "Test Sets", "op": "$contains", "value": ["test_sets/milestones/%s/" % text]},
        {"field": "Team", "op": "$eq", "value": ["%s/%s" % (text, _TEAM)]},
        {"field": "Test Sets", "op": "$contains", "value": ["test_sets/milestones/%s/%s/" % (text, _TEAM)]},
    ]
    if kind == "feat":
        filters.append({"field": "Release", "op": "$eq", "value": [text]})
        filters.append({"field": "Tags", "op": "$nin", "value": list(_EXCLUDED_TAGS)})
    elif kind == "regression":
        filters.append({"field": "Release", "op": "$ne", "value": [text]})
        filters.append({"field": "Tags", "op": "$nin", "value": list(_EXCLUDED_TAGS)})
    return filters


def _tcms_search_url(text, kind, extra, tail):
    filters = _tcms_filters(text, kind) + list(extra or [])
    search = quote(json.dumps(filters, separators=(",", ":")), safe="")
    return "%s%s?search=%s&%s" % (TCMS_UI, text, search, tail)


def tcms_page_url(milestone, raw_type):
    kind = view_type(raw_type)
    text = (milestone or "").strip()
    tail = "pass=overall"
    if kind != "feat":
        tail += "&tab=package_type"
    tail += "&type=%s" % _VIEW_LABEL[kind]
    return _tcms_search_url(text, kind, [], tail)


def tcms_components_url(milestone, raw_type):
    kind = view_type(raw_type)
    text = (milestone or "").strip()
    tail = "pass=overall&tab=test_case.metadata.components&type=%s" % _VIEW_LABEL[kind]
    return _tcms_search_url(text, kind, [], tail)


def component_bugs_url(milestone, raw_type, component):
    kind = view_type(raw_type)
    text = (milestone or "").strip()
    extra = [{"field": "Components", "op": "$eq", "value": [component]}]
    tail = "tab=bugs&pass=overall&type=%s&bug_types=%s" % (_VIEW_LABEL[kind], _BUG_TYPES)
    return _tcms_search_url(text, kind, extra, tail)


def qi_tone(value):
    """Below 85 is red, below 90 is yellow, and 90 or above is green."""
    if value is None:
        return ""
    if value < 85:
        return "red"
    if value < 90:
        return "yellow"
    return "green"


def _published_qi(item):
    last_result = item.get("last_result")
    if not isinstance(last_result, list):
        return None
    chosen = None
    for entry in last_result:
        if isinstance(entry, dict) and str(entry.get("pass_name") or "").lower() == "overall":
            chosen = entry
            break
    if chosen is None and last_result and isinstance(last_result[0], dict):
        chosen = last_result[0]
    if not isinstance(chosen, dict):
        return None
    published = chosen.get("published")
    if not isinstance(published, dict):
        return None
    value = published.get("operation_success_percentage")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _component_names(item):
    """Every TCMS component, or the primary component when that list is empty."""
    tc = item.get("test_case") if isinstance(item.get("test_case"), dict) else {}
    meta = tc.get("metadata") if isinstance(tc.get("metadata"), dict) else {}
    raw = meta.get("components")
    if isinstance(raw, str):
        raw = [raw]
    names = []
    for entry in raw or []:
        if isinstance(entry, dict):
            text = str(entry.get("name") or entry.get("component") or "").strip()
        else:
            text = str(entry or "").strip()
        if text and text not in names:
            names.append(text)
    if not names:
        primary = str(meta.get("primary_component") or "").strip()
        if primary:
            names.append(primary)
    return names or ["Unknown"]


def _component_name(item):
    return _component_names(item)[0]


def _jira_id(ticket):
    text = str(ticket or "").strip()
    match = _JIRA_RE.search(text)
    return match.group(0).upper() if match else text


def _jira_ids(raw):
    ids = []
    for ticket in _ticket_ids(raw):
        jira = _jira_id(ticket)
        if jira and jira not in ids:
            ids.append(jira)
    return ids


def _triaged(run):
    value = run.get("is_triaged") if isinstance(run, dict) else None
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _merge_components(existing, incoming):
    if "components" not in incoming and "component" not in incoming:
        return
    names = list(existing.get("components") or [])
    if not names and existing.get("component"):
        names = [existing["component"]]
    for name in incoming.get("components") or []:
        if name and name not in names:
            names.append(name)
    if not names and incoming.get("component"):
        names = [incoming["component"]]
    concrete = [name for name in names if name != "Unknown"]
    names = concrete or names or ["Unknown"]
    existing["components"] = names
    existing["component"] = names[0]


def _prefer_result(existing, incoming):
    if _RESULT_RANK[incoming["result"]] > _RESULT_RANK[existing["result"]]:
        existing["status"] = incoming["status"]
        existing["result"] = incoming["result"]
        existing["tickets"] = list(incoming.get("tickets") or [])
        existing["triaged"] = bool(incoming.get("triaged"))
    elif not existing.get("tickets") and incoming.get("tickets"):
        existing["tickets"] = list(incoming["tickets"])
    if incoming.get("triaged"):
        existing["triaged"] = True
    if existing.get("qi") is None and incoming.get("qi") is not None:
        existing["qi"] = incoming["qi"]
    _merge_components(existing, incoming)
    for label in incoming.get("tags") or []:
        tags = existing.setdefault("tags", [])
        if label not in tags:
            tags.append(label)


def summary_records(rows):
    """One row per test name. A pass beats a fail, which beats no result."""
    by_name = {}
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        tc = item.get("test_case") if isinstance(item.get("test_case"), dict) else {}
        name = str(item.get("name") or tc.get("name") or "").strip()
        if not name:
            continue
        run = _branch_run(item)
        status = str(run.get("status") or "").strip()
        components = _component_names(item)
        record = {
            "name": name,
            "status": status,
            "result": _result_kind(status),
            "qi": _published_qi(item),
            "component": components[0],
            "components": components,
            "triaged": _triaged(run),
            "tickets": _ticket_ids(run.get("tickets")) or _ticket_ids(item.get("tickets")),
            "tags": [],
        }
        key = name.lower()
        current = by_name.get(key)
        if current is None:
            by_name[key] = record
        else:
            _prefer_result(current, record)
    return list(by_name.values())


def _execution(records):
    passed = sum(1 for rec in records if rec["result"] == "pass")
    failed = sum(1 for rec in records if rec["result"] == "fail")
    not_run = len(records) - passed - failed
    qi_values = [rec["qi"] for rec in records if rec.get("qi") is not None]
    executed = passed + failed
    return {
        "total": len(records),
        "passed": passed,
        "failed": failed,
        "not_run": not_run,
        "run_percentage": round((100.0 * executed) / len(records), 1) if records else 0,
        "qi": round(sum(qi_values) / len(qi_values), 2) if qi_values else None,
        "qi_source": "tcms_rows" if qi_values else None,
    }


def _record_components(rec):
    names = list(rec.get("components") or [])
    if not names and rec.get("component"):
        names = [rec["component"]]
    return names or ["Unknown"]


def _components(records, milestone, raw_type):
    """One TCMS component row. A test is counted under every component it lists."""
    buckets = {}
    for rec in records:
        for name in _record_components(rec):
            bucket = buckets.get(name)
            if bucket is None:
                bucket = {
                    "component": name,
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "not_run": 0,
                    "triaged": 0,
                    "qi_sum": 0.0,
                    "qi_count": 0,
                    "open_bugs": [],
                }
                buckets[name] = bucket
            bucket["total"] += 1
            if rec["result"] == "pass":
                bucket["passed"] += 1
            elif rec["result"] == "fail":
                bucket["failed"] += 1
                if rec.get("triaged"):
                    bucket["triaged"] += 1
                for ticket in _jira_ids(rec.get("tickets")):
                    if ticket not in bucket["open_bugs"]:
                        bucket["open_bugs"].append(ticket)
            else:
                bucket["not_run"] += 1
            if rec.get("qi") is not None:
                bucket["qi_sum"] += rec["qi"]
                bucket["qi_count"] += 1
    ordered = []
    for bucket in buckets.values():
        count = bucket.pop("qi_count")
        total_qi = bucket.pop("qi_sum")
        failed = bucket["failed"]
        qi = round(total_qi / count, 1) if count else None
        bucket["run"] = bucket["passed"] + failed
        bucket["qi"] = qi
        bucket["qi_tone"] = qi_tone(qi)
        bucket["qi_source"] = "tcms_rows"
        bucket["triaged_percentage"] = round((100.0 * bucket.pop("triaged")) / failed, 1) if failed else None
        open_bugs = bucket["open_bugs"]
        bucket["open_bug_count"] = len(open_bugs)
        bucket["open_bugs"] = open_bugs[:_LIST_LIMIT]
        bucket["bugs_url"] = component_bugs_url(milestone, raw_type, bucket["component"])
        ordered.append(bucket)
    ordered.sort(key=lambda item: (-item["total"], item["component"].lower()))
    return ordered


def _handover(rows, milestone, root, branch):
    info = release_info(milestone, root=root, branch=branch)
    if not info:
        return None
    dashboard = build_dashboard(rows, milestone, root=info["root"], branch=info["branch"])
    feats = dashboard.get("feats") or []
    tests_total = sum(feat["total"] for feat in feats)
    handed = sum(feat["handed_over"] for feat in feats)
    return {
        "feat_count": dashboard.get("feat_count") or 0,
        "pending_feats": (dashboard.get("summary") or {}).get("black") or 0,
        "tests_not_handed_over": tests_total - handed,
        "tests_not_run": sum(feat["not_run"] for feat in feats),
        "handed_over_tests": handed,
        "feat_total_tests": tests_total,
    }


def build_summary(rows, milestone, raw_type, root=None, branch=None):
    kind = view_type(raw_type)
    records = summary_records(rows)
    payload = {
        "milestone": milestone,
        "type": kind,
        "team": _TEAM,
        "show_regression": kind in ("all", "regression"),
        "show_handover": kind in ("all", "feat"),
        "execution": _execution(records),
        "components": _components(records, milestone, kind),
        "components_url": tcms_components_url(milestone, kind),
        "handover": _handover(rows, milestone, root, branch) if kind in ("all", "feat") else None,
        "tcms_url": tcms_page_url(milestone, kind),
    }
    return payload


def apply_metrics_qi(summary, metrics):
    """Replace the summary counts with the TCMS aggregate for this type."""
    if not isinstance(metrics, dict):
        return summary
    summary["metrics"] = {
        "qi": metrics.get("qi"),
        "total": metrics.get("total"),
        "run": metrics.get("run"),
        "passed": metrics.get("passed"),
        "failed": metrics.get("failed"),
        "not_run": metrics.get("not_run"),
        "run_percentage": metrics.get("run_percentage"),
        "triage_percentage": metrics.get("triage_percentage"),
        "total_triaged": metrics.get("total_triaged"),
    }
    execution = summary.get("execution") or {}
    for key in (
        "total", "run", "passed", "failed", "not_run", "run_percentage",
        "triage_percentage", "total_triaged", "qi",
    ):
        if metrics.get(key) is not None:
            execution[key] = metrics[key]
    if metrics.get("qi") is not None:
        execution["qi_source"] = "tcms_metrics"
    summary["execution"] = execution
    return summary


def fetch_summary_rows(milestone, raw_type):
    match = summary_match(milestone, raw_type)
    rows = []
    for page in range(_MAX_PAGES):
        payload = [
            {"$match": match},
            {"$project": {
                "name": 1,
                "tickets": 1,
                "release_name": 1,
                "test_case.name": 1,
                "test_case.test_sets": 1,
                "test_case.owners": 1,
                "test_case.metadata.primary_component": 1,
                "test_case.metadata.components": 1,
                "test_case.metadata.tags": 1,
                "last_result": 1,
            }},
            {"$skip": page * _PAGE_SIZE},
            {"$limit": _PAGE_SIZE},
        ]
        try:
            response = requests.post(
                "%s/milestone_all_test_cases/aggregate" % TCMS_BASE,
                json=payload,
                auth=(TCMS_USER, TCMS_PASSWORD),
                headers={"Content-Type": "application/json"},
                verify=False,
                timeout=120,
            )
        except requests.RequestException as exc:
            logger.warning("TCMS summary request failed: %s", exc)
            raise DashboardError("TCMS request failed")
        if response.status_code != 200:
            logger.warning("TCMS summary HTTP %s", response.status_code)
            raise DashboardError("TCMS returned HTTP %s" % response.status_code)
        try:
            body = response.json()
        except ValueError:
            raise DashboardError("TCMS returned a non-JSON response")
        batch = body.get("data") if isinstance(body, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
    return rows


def fetch_summary_metrics(milestone, raw_type):
    kind = view_type(raw_type)
    feat_type = {"all": "all", "feat": "feat", "regression": "regression"}[kind]
    params = {
        "aggregation_field": "target_package_type",
        "time_filter": "all",
        "target_milestone": milestone,
        "feat_type": feat_type,
        "filters": json.dumps(component_metrics_match(milestone, kind)),
    }
    try:
        response = requests.get(
            "%s/milestone_all_test_cases/aggregate/metrics" % TCMS_SUMMARY_BASE,
            params=params,
            headers={"Content-Type": "application/json"},
            verify=False,
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("TCMS summary metrics failed: %s", exc)
        return None
    if response.status_code != 200:
        logger.warning("TCMS summary metrics HTTP %s", response.status_code)
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    overall = data[0]
    for row in data:
        if isinstance(row, dict) and row.get("_id") == "overall":
            overall = row
            break
    return {
        "qi": overall.get("average_total_op_success_percentage"),
        "total": overall.get("total"),
        "run": overall.get("run"),
        "passed": overall.get("passed"),
        "failed": overall.get("failed"),
        "not_run": overall.get("not_run"),
        "run_percentage": overall.get("run_percentage"),
        "triage_percentage": overall.get("triage_percentage"),
        "total_triaged": overall.get("total_triaged"),
    }


def component_metrics_match(milestone, raw_type):
    """Filters that match the Open TCMS components link for this type."""
    kind = view_type(raw_type)
    text = (milestone or "").strip()
    if not _MILESTONE_RE.match(text):
        raise DashboardError("Unsupported release")
    broad = "test_sets/milestones/%s/" % text
    team_path = "test_sets/milestones/%s/%s/" % (text, _TEAM)
    clauses = [
        {"additional_data.team": "%s/%s" % (text, _TEAM)},
        {"test_case.test_sets": {"$regex": re.escape(broad), "$options": "i"}},
        {"test_case.test_sets": {"$regex": re.escape(team_path), "$options": "i"}},
        {"test_case.deprecated": False},
    ]
    if kind == "feat":
        clauses.append({"release_name": text})
        clauses.append({"test_case.metadata.tags": {"$nin": list(_EXCLUDED_TAGS)}})
    elif kind == "regression":
        clauses.append({"release_name": {"$ne": text}})
        clauses.append({"test_case.metadata.tags": {"$nin": list(_EXCLUDED_TAGS)}})
    return {"$and": clauses}


def _metric_component_name(row):
    for key in ("_id", "name", "component", "key", "test_case.metadata.components"):
        value = row.get(key)
        if isinstance(value, dict):
            value = value.get("field_name") or value.get("name") or value.get("component") or ""
        if isinstance(value, list):
            value = value[0] if value else ""
        text = str(value or "").strip()
        if text and text.lower() not in ("overall", "null", "none"):
            return text
    return ""


def _metric_qi(row):
    value = row.get("average_total_op_success_percentage")
    if value is None:
        value = row.get("qi")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _metric_int(row, key):
    value = row.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _apply_metric_counts(component, row):
    for key in ("total", "run", "not_run", "passed", "failed", "total_triaged"):
        value = _metric_int(row, key)
        if value is not None:
            component[key] = value
    triage = row.get("triage_percentage")
    if triage is not None:
        try:
            component["triaged_percentage"] = float(triage)
        except (TypeError, ValueError):
            pass
    if row.get("unique_tickets") is not None:
        tickets = _jira_ids(row.get("unique_tickets"))
        component["open_bugs"] = tickets[:_LIST_LIMIT]
        if row.get("openBugs") is None:
            component["open_bug_count"] = len(tickets)
    open_bugs = _metric_int(row, "openBugs")
    if open_bugs is not None:
        component["open_bug_count"] = open_bugs


def apply_component_metrics(components, metric_rows, milestone=None, raw_type=None):
    """Replace component columns with the TCMS components-tab aggregate."""
    if not isinstance(components, list):
        components = []
    by_row = {}
    for row in metric_rows or []:
        if not isinstance(row, dict):
            continue
        name = _metric_component_name(row)
        if name:
            by_row[name.lower()] = row
    seen = set()
    for component in components:
        name = str(component.get("component") or "")
        row = by_row.get(name.lower())
        if row is None:
            component["qi_source"] = "tcms_rows"
            continue
        seen.add(name.lower())
        qi = _metric_qi(row)
        if qi is not None:
            component["qi"] = qi
            component["qi_tone"] = qi_tone(qi)
        _apply_metric_counts(component, row)
        component["qi_source"] = "tcms_metrics"
    for key, row in by_row.items():
        if key in seen:
            continue
        name = _metric_component_name(row)
        qi = _metric_qi(row)
        component = {
            "component": name,
            "qi": qi,
            "qi_tone": qi_tone(qi) if qi is not None else "",
            "qi_source": "tcms_metrics",
            "bugs_url": component_bugs_url(milestone, raw_type, name) if milestone and raw_type else "",
            "open_bugs": [],
            "open_bug_count": 0,
        }
        _apply_metric_counts(component, row)
        components.append(component)
    components.sort(key=lambda item: (-(item.get("total") or 0), str(item.get("component") or "").lower()))
    return components


def fetch_component_metrics(milestone, raw_type):
    kind = view_type(raw_type)
    feat_type = {"all": "all", "feat": "feat", "regression": "regression"}[kind]
    params = {
        "aggregation_field": "test_case.metadata.components",
        "time_filter": "all",
        "target_milestone": milestone,
        "feat_type": feat_type,
        "filters": json.dumps(component_metrics_match(milestone, kind)),
    }
    try:
        response = requests.get(
            "%s/milestone_all_test_cases/aggregate/metrics" % TCMS_SUMMARY_BASE,
            params=params,
            headers={"Content-Type": "application/json"},
            verify=False,
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("TCMS component metrics failed: %s", exc)
        return None
    if response.status_code != 200:
        logger.warning("TCMS component metrics HTTP %s", response.status_code)
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return None
    return data


def tags_path(path=None):
    if path:
        return path
    override = (os.environ.get("REGX_TEAM_DATA_DIR") or "").strip()
    if override:
        return os.path.join(override, "release_dashboard_jita_tags.json")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "CDP_FT", "release_dashboard_jita_tags.json")


def _read_tag_file(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read JITA tag file: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def normalize_tags(raw):
    if not isinstance(raw, list):
        raise DashboardError("tags must be a list")
    if len(raw) > _MAX_TAGS:
        raise DashboardError("At most %s tags" % _MAX_TAGS)
    cleaned = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        tag = str(item.get("tag") or "").strip()
        if not label and not tag:
            continue
        if not label or not tag:
            raise DashboardError("Each tag needs a label and a JITA tag")
        if len(label) > 64 or not _TAG_NAME_RE.match(tag):
            raise DashboardError("Unsupported tag label or name")
        key = (label.lower(), tag)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"label": label, "tag": tag})
    return cleaned


def load_jita_tags(milestone, path=None):
    text = (milestone or "").strip()
    if not _MILESTONE_RE.match(text):
        raise DashboardError("Unsupported release")
    data = _read_tag_file(tags_path(path))
    tags = data.get(text) or []
    return normalize_tags(tags) if isinstance(tags, list) else []


def save_jita_tags(milestone, raw_tags, path=None):
    text = (milestone or "").strip()
    if not _MILESTONE_RE.match(text):
        raise DashboardError("Unsupported release")
    tags = normalize_tags(raw_tags)
    dest = tags_path(path)
    folder = os.path.dirname(dest)
    if folder:
        os.makedirs(folder, exist_ok=True)
    data = _read_tag_file(dest)
    data[text] = tags
    temporary = dest + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, dest)
    return tags


def _jita_name(row):
    test = row.get("test") if isinstance(row, dict) else None
    if isinstance(test, dict):
        return str(test.get("name") or "").strip()
    if isinstance(row, dict):
        return str(row.get("name") or "").strip()
    return ""


def _index_results(rows, label):
    indexed = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = _jita_name(row)
        if not name:
            continue
        status = str(row.get("status") or "").strip()
        incoming = {
            "name": name,
            "status": status,
            "result": _result_kind(status),
            "qi": None,
            "component": "",
            "tickets": [],
            "tags": [label] if label else [],
        }
        key = name.lower()
        current = indexed.get(key)
        if current is None:
            indexed[key] = incoming
        else:
            _prefer_result(current, incoming)
    return indexed


def _rollup(indexed):
    return _execution(list(indexed.values()))


def _pack(items):
    ordered = sorted(items, key=lambda item: item.get("name", "").lower())
    return {"count": len(ordered), "items": ordered[:_LIST_LIMIT]}


def build_comparison(tcms_records, tag_results):
    """Compare the TCMS set with the union of JITA tag results.

    A pass on any tag wins over a fail. TCMS stays the release record:
    missing JITA rows, not-run rows that JITA already finished, pass/fail
    disagreements, and JITA rows outside the TCMS type are called out.
    """
    tcms = {}
    for rec in tcms_records or []:
        key = rec["name"].lower()
        current = tcms.get(key)
        if current is None:
            tcms[key] = dict(rec)
        else:
            _prefer_result(current, rec)

    per_tag = []
    union = {}
    for spec in tag_results or []:
        label = spec.get("label") or spec.get("tag") or ""
        indexed = _index_results(spec.get("tests") or [], label)
        counts = _rollup(indexed)
        counts.update({
            "label": label,
            "tag": spec.get("tag") or "",
            "task_count": spec.get("task_count") or 0,
            "error": spec.get("error") or "",
        })
        per_tag.append(counts)
        for key, record in indexed.items():
            current = union.get(key)
            if current is None:
                union[key] = dict(record)
            else:
                _prefer_result(current, record)

    not_triggered = []
    sync_gap = []
    status_mismatch = []
    matched = 0
    for key, rec in tcms.items():
        other = union.get(key)
        if other is None:
            not_triggered.append({
                "name": rec["name"],
                "tcms_status": rec.get("status") or "",
                "jita_status": "",
                "jita_tags": [],
            })
            continue
        jita_definitive = other["result"] in ("pass", "fail")
        tcms_definitive = rec["result"] in ("pass", "fail")
        if rec["result"] == "other" and (other.get("status") or jita_definitive):
            sync_gap.append({
                "name": rec["name"],
                "tcms_status": rec.get("status") or "",
                "jita_status": other.get("status") or "",
                "jita_tags": list(other.get("tags") or []),
            })
            continue
        if tcms_definitive and jita_definitive and rec["result"] != other["result"]:
            status_mismatch.append({
                "name": rec["name"],
                "tcms_status": rec.get("status") or "",
                "jita_status": other.get("status") or "",
                "jita_tags": list(other.get("tags") or []),
            })
            continue
        matched += 1

    outside = []
    for key, rec in union.items():
        if key in tcms:
            continue
        outside.append({
            "name": rec["name"],
            "tcms_status": "",
            "jita_status": rec.get("status") or "",
            "jita_tags": list(rec.get("tags") or []),
        })

    return {
        "per_tag": per_tag,
        "combined": _rollup(union),
        "tcms_total": len(tcms),
        "matched_count": matched,
        "not_triggered": _pack(not_triggered),
        "sync_gap": _pack(sync_gap),
        "status_mismatch": _pack(status_mismatch),
        "outside_tcms": _pack(outside),
        "components": active_bugs_by_component(list(tcms.values()), latest_jita_by_test(tag_results)),
    }


def _epoch(value):
    if value is None or value == "":
        return 0
    if isinstance(value, dict):
        return _epoch(value.get("$date"))
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return float(text)
    except ValueError:
        pass
    try:
        cleaned = text.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).timestamp() * 1000
    except ValueError:
        return 0


def _task_time(task):
    if not isinstance(task, dict):
        return 0
    end = _epoch(task.get("end_time"))
    if end:
        return end
    return _epoch(task.get("created_at"))


def _result_task_oid(row):
    raw = row.get("agave_task_id") if isinstance(row, dict) else None
    if isinstance(raw, dict):
        return str(raw.get("$oid") or "").strip()
    return str(raw or "").strip()


def _jita_tickets(row):
    if not isinstance(row, dict):
        return []
    return _jira_ids(row.get("jira_tickets") or row.get("tickets") or [])


def latest_jita_by_test(tag_results):
    """Newest JITA result per test. end_time wins, then created_at, then task id."""
    latest = {}
    for spec in tag_results or []:
        label = spec.get("label") or spec.get("tag") or ""
        for row in spec.get("tests") or []:
            if not isinstance(row, dict):
                continue
            name = _jita_name(row)
            if not name:
                continue
            task_time = _epoch(row.get("task_time"))
            oid = _result_task_oid(row)
            incoming = {
                "name": name,
                "status": str(row.get("status") or "").strip(),
                "tickets": _jita_tickets(row),
                "task_time": task_time,
                "task_id": oid,
                "tag": label,
            }
            key = name.lower()
            current = latest.get(key)
            if current is None or (task_time, oid) > (current["task_time"], current["task_id"]):
                latest[key] = incoming
    return latest


def _qi_number(rec):
    value = rec.get("qi")
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def active_bugs_by_component(records, latest_jita):
    """Active tickets are those tagged on the latest JITA result.

    The same TCMS ticket stays active. A different JITA ticket replaces it
    as the active bug. No JITA ticket means the TCMS bug is not active.
    Top QI bugs use the active ticket when JITA has one, otherwise the TCMS ticket.
    """
    latest = latest_jita or {}
    buckets = {}
    for rec in records or []:
        for name in _record_components(rec):
            bucket = buckets.setdefault(name, {"tests": [], "names": set()})
            bucket["tests"].append(rec)
            bucket["names"].add(rec["name"].lower())

    rows = []
    for name, bucket in buckets.items():
        active = {}
        impact = {}
        for rec in bucket["tests"]:
            jita = latest.get(rec["name"].lower())
            tcms_ids = _jira_ids(rec.get("tickets"))
            jita_ids = list((jita or {}).get("tickets") or [])
            if jita_ids:
                for ticket in jita_ids:
                    match = "same" if ticket in tcms_ids else "different"
                    slot = active.setdefault(ticket, {"ticket": ticket, "match": "same", "tests": []})
                    if match == "different":
                        slot["match"] = "different"
                    if rec["name"] not in slot["tests"]:
                        slot["tests"].append(rec["name"])
                group_ids = jita_ids
            else:
                group_ids = tcms_ids
            if rec.get("result") != "fail":
                continue
            for ticket in group_ids:
                group = impact.setdefault(ticket, {"ticket": ticket, "tests": [], "qi": []})
                if rec["name"] not in group["tests"]:
                    group["tests"].append(rec["name"])
                    group["qi"].append(_qi_number(rec))
        active_bugs = sorted(active.values(), key=lambda item: item["ticket"])
        total_tests = len(bucket["names"]) or 1
        ranked = []
        for group in impact.values():
            count = len(group["tests"])
            average = sum(group["qi"]) / count if count else 0
            qi_impact = (average - 100) * count
            ranked.append({
                "ticket": group["ticket"],
                "tests": group["tests"][:_LIST_LIMIT],
                "testcase_count": count,
                "average_qi": round(average, 2),
                "qi_impact": round(qi_impact, 2),
                "overall_qi_impact": round(100 * (qi_impact / (100 * total_tests)), 2),
            })
        ranked.sort(key=lambda item: (item["qi_impact"], item["ticket"]))
        rows.append({
            "component": name,
            "active_count": len(active_bugs),
            "active_bugs": active_bugs,
            "top_qi": ranked[:_TOP_QI],
        })
    rows.sort(key=lambda item: item["component"].lower())
    return rows


def bulk_tickets(records, minimum=_BULK_MIN):
    """Tickets on more than `minimum` failed tests. Home uses more than 5."""
    groups = {}
    for rec in records or []:
        if rec.get("result") != "fail":
            continue
        for ticket in rec.get("tickets") or []:
            groups.setdefault(ticket, set()).add(rec["name"])
    return {
        ticket: sorted(names)
        for ticket, names in groups.items()
        if len(names) > minimum
    }


def _task_oid(task):
    raw = task.get("_id") if isinstance(task, dict) else None
    if isinstance(raw, dict):
        return str(raw.get("$oid") or "").strip()
    return str(raw or "").strip()


def _collect_tag_results(tags):
    if _fetch_tasks is None or _fetch_results is None:
        raise DashboardError("JITA lookup is not available")
    collected = []
    for spec in tags:
        label = spec["label"]
        tag = spec["tag"]
        entry = {"label": label, "tag": tag, "task_count": 0, "tests": [], "error": ""}
        try:
            tasks = _fetch_tasks(tag=tag) or []
            ids = []
            times = {}
            for task in tasks:
                oid = _task_oid(task)
                if oid and oid not in ids:
                    ids.append(oid)
                if oid:
                    times[oid] = _task_time(task)
            entry["task_count"] = len(ids)
            if ids:
                stamped = []
                for row in _fetch_results(ids) or []:
                    if not isinstance(row, dict):
                        continue
                    copied = dict(row)
                    copied["task_time"] = times.get(_result_task_oid(row), 0)
                    stamped.append(copied)
                entry["tests"] = stamped
        except Exception as exc:
            logger.warning("JITA tag %s failed: %s", tag, exc)
            entry["error"] = str(exc)
        collected.append(entry)
    return collected


def _milestone_arg():
    milestone = (request.args.get("milestone") or "").strip()
    if not milestone and request.method != "GET":
        body = request.get_json(silent=True) or {}
        milestone = str(body.get("milestone") or "").strip()
    if not _MILESTONE_RE.match(milestone):
        return None
    return milestone


def _summary_context():
    """Milestone, type, and optional feat-tree root from the query or body."""
    if request.method == "GET":
        source = request.args
    else:
        source = request.get_json(silent=True) or {}
    milestone = str(source.get("milestone") or "").strip()
    if not _MILESTONE_RE.match(milestone):
        raise DashboardError("Unsupported release")
    kind = view_type(source.get("type") or source.get("view") or "all")
    root = str(source.get("root") or "").strip()
    branch = str(source.get("branch") or "").strip()
    info = release_info(milestone, root=root or None, branch=branch or None)
    return milestone, kind, info


def register_routes(app, jwt_required, fetch_tasks=None, fetch_results=None, qi_impact=None):
    global _fetch_tasks, _fetch_results, _qi_impact
    if fetch_tasks is not None:
        _fetch_tasks = fetch_tasks
    if fetch_results is not None:
        _fetch_results = fetch_results
    if qi_impact is not None:
        _qi_impact = qi_impact
    @app.route("/mcp/regression/release-dashboard", methods=["GET"])
    @app.route("/api/mcp/regression/release-dashboard", methods=["GET"])
    @jwt_required
    def release_dashboard_status():
        milestone = (request.args.get("milestone") or "7.7").strip()
        root = (request.args.get("root") or "").strip()
        branch = (request.args.get("branch") or "").strip()
        if not _MILESTONE_RE.match(milestone):
            return jsonify({"error": "Unsupported release"}), 400
        if milestone not in RELEASES and not root:
            return jsonify({
                "error": "Add this release with + so its feat folder can be found.",
            }), 400
        info = release_info(milestone, root=root or None, branch=branch or None)
        if not info:
            return jsonify({"error": "Unsupported release"}), 400
        try:
            rows = fetch_milestone_rows(info["milestone"], root=info["root"], branch=info["branch"])
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify(build_dashboard(
            rows, info["milestone"], root=info["root"], branch=info["branch"],
        ))

    @app.route("/mcp/regression/release-dashboard/lookup", methods=["POST"])
    @app.route("/api/mcp/regression/release-dashboard/lookup", methods=["POST"])
    @jwt_required
    def release_dashboard_lookup():
        body = request.get_json(silent=True) or {}
        nos = body.get("nos") or body.get("milestone") or ""
        try:
            info = lookup_release(nos)
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(info)

    @app.route("/mcp/regression/release-dashboard/summary", methods=["GET"])
    @app.route("/api/mcp/regression/release-dashboard/summary", methods=["GET"])
    @jwt_required
    def release_dashboard_summary():
        try:
            milestone, kind, info = _summary_context()
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 400
        root = info["root"] if info else None
        branch = info["branch"] if info else None
        try:
            rows = fetch_summary_rows(milestone, kind)
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 502
        payload = build_summary(rows, milestone, kind, root=root, branch=branch)
        apply_metrics_qi(payload, fetch_summary_metrics(milestone, kind))
        payload["components"] = apply_component_metrics(
            payload.get("components"),
            fetch_component_metrics(milestone, kind),
            milestone=milestone,
            raw_type=kind,
        )
        return jsonify(payload)

    @app.route("/mcp/regression/release-dashboard/jita-tags", methods=["GET"])
    @app.route("/api/mcp/regression/release-dashboard/jita-tags", methods=["GET"])
    @jwt_required
    def release_dashboard_jita_tags_get():
        milestone = _milestone_arg()
        if not milestone:
            return jsonify({"error": "Unsupported release"}), 400
        try:
            tags = load_jita_tags(milestone)
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({
            "milestone": milestone,
            "presets": list(_TAG_PRESETS),
            "tags": tags,
        })

    @app.route("/mcp/regression/release-dashboard/jita-tags", methods=["PUT"])
    @app.route("/api/mcp/regression/release-dashboard/jita-tags", methods=["PUT"])
    @jwt_required
    def release_dashboard_jita_tags_put():
        body = request.get_json(silent=True) or {}
        milestone = str(body.get("milestone") or "").strip()
        if not _MILESTONE_RE.match(milestone):
            return jsonify({"error": "Unsupported release"}), 400
        try:
            tags = save_jita_tags(milestone, body.get("tags") or [])
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"milestone": milestone, "presets": list(_TAG_PRESETS), "tags": tags})

    @app.route("/mcp/regression/release-dashboard/compare", methods=["POST"])
    @app.route("/api/mcp/regression/release-dashboard/compare", methods=["POST"])
    @jwt_required
    def release_dashboard_compare():
        try:
            milestone, kind, info = _summary_context()
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            tags = load_jita_tags(milestone)
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 400
        if not tags:
            return jsonify({
                "milestone": milestone,
                "type": kind,
                "needs_tags": True,
                "tags": [],
                "comparison": None,
            })
        try:
            rows = fetch_summary_rows(milestone, kind)
            tag_results = _collect_tag_results(tags)
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 502
        comparison = build_comparison(summary_records(rows), tag_results)
        return jsonify({
            "milestone": milestone,
            "type": kind,
            "needs_tags": False,
            "tags": tags,
            "branch": info["branch"] if info else "",
            "comparison": comparison,
        })

    @app.route("/mcp/regression/release-dashboard/top-qi", methods=["POST"])
    @app.route("/api/mcp/regression/release-dashboard/top-qi", methods=["POST"])
    @jwt_required
    def release_dashboard_top_qi():
        try:
            milestone, kind, _info = _summary_context()
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 400
        if _qi_impact is None:
            return jsonify({"error": "QI lookup is not available"}), 500
        try:
            rows = fetch_summary_rows(milestone, kind)
        except DashboardError as exc:
            return jsonify({"error": str(exc)}), 502
        records = summary_records(rows)
        grouped = bulk_tickets(records)
        test_data = []
        for rec in records:
            if rec["result"] == "pass":
                status = "Succeeded"
            elif rec["result"] == "fail":
                status = "Failed"
            else:
                status = rec.get("status") or ""
            test_data.append({"test": {"name": rec["name"]}, "status": status})
        try:
            qi = _qi_impact(grouped, test_data, tag=milestone) or {}
        except Exception as exc:
            logger.warning("Top QI lookup failed: %s", exc)
            return jsonify({"error": "QI lookup failed"}), 502
        with_qi = qi.get("bulk_issues_with_qi") or {}
        bugs = []
        for ticket, names in grouped.items():
            detail = with_qi.get(ticket) or {}
            bugs.append({
                "ticket": ticket,
                "tests": names,
                "testcase_count": len(names),
                "average_qi": detail.get("average_qi"),
                "qi_impact": detail.get("qi_impact"),
                "overall_qi_impact": detail.get("overall_qi_impact"),
            })
        bugs.sort(key=lambda bug: (
            bug.get("overall_qi_impact") is None,
            bug.get("overall_qi_impact") if bug.get("overall_qi_impact") is not None else 0,
        ))
        return jsonify({
            "milestone": milestone,
            "type": kind,
            "bulk_issues": grouped,
            "bugs": bugs,
        })
