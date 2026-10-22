"""Read-only CDP feat status for one release.

Rows come from the TCMS milestone aggregate. Feat folders are the directories
directly under the Sourcegraph tree for that release. A sibling whose name
starts with REGRESSION is the handover folder, not a feat. intransit paths
do not count. This module does not write anything.
"""
import logging
import os
import re

import requests
from flask import jsonify, request

logger = logging.getLogger(__name__)

TCMS_BASE = os.getenv("TCMS_BASE", "https://tcms.eng.nutanix.com/api-readonly/v1").rstrip("/")
TCMS_USER = os.getenv("TCMS_USER", "agave_bot")
TCMS_PASSWORD = os.getenv("TCMS_PASSWORD", "admin")

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


class DashboardError(Exception):
    pass


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


def _overall_run(item):
    last_result = item.get("last_result")
    if not isinstance(last_result, list):
        return {}
    chosen = None
    for entry in last_result:
        if isinstance(entry, dict) and str(entry.get("pass_name") or "").lower() == "overall":
            chosen = entry
            break
    if chosen is None:
        chosen = last_result[0] if last_result and isinstance(last_result[0], dict) else None
    if not isinstance(chosen, dict):
        return {}
    run = chosen.get("run")
    return run if isinstance(run, dict) else {}


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
    run = _overall_run(item)
    tickets = _ticket_ids(run.get("tickets")) or _ticket_ids(item.get("tickets"))
    return {
        "name": name,
        "in_regression": in_regression,
        "status": str(run.get("status") or "").strip(),
        "issue_type": str(run.get("issue_type") or "").strip(),
        "tickets": tickets,
        "owners": _owners(tc.get("owners")),
        "feats": feats,
    }


def _merge_test(existing, incoming):
    existing["in_regression"] = existing["in_regression"] or incoming["in_regression"]
    if not existing["status"] and incoming["status"]:
        existing["status"] = incoming["status"]
        existing["issue_type"] = incoming["issue_type"]
        existing["tickets"] = incoming["tickets"]
    if not existing["owners"] and incoming["owners"]:
        existing["owners"] = incoming["owners"]
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


def register_routes(app, jwt_required):
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
