"""Unit tests for Testcase Management tag add/delete helpers."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_helpers():
    """Load tag helpers from test_flask without starting the Flask app server loop."""
    import importlib.util
    from types import SimpleNamespace

    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    # Extract helper block between markers (include branch normalize)
    start = src.index("def _normalize_tc_branch_key(")
    end = src.index("def _build_aggregate_payload(")
    chunk = src[start:end]

    ns = {
        "os": os,
        "re": __import__("re"),
        "json": __import__("json"),
        "urllib": __import__("urllib"),
        "requests": __import__("requests"),
        "datetime": __import__("datetime").datetime,
        "ThreadPoolExecutor": __import__("concurrent.futures").futures.ThreadPoolExecutor,
        "as_completed": __import__("concurrent.futures").futures.as_completed,
        "_DOTTED_VERSION_RE": __import__("re").compile(r"\d+(?:\.\d+)+"),
        "logger": SimpleNamespace(
            warning=lambda *a, **k: None,
            info=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
        "TCMS_TESTDB_BASE": "https://testdb.example/api/v1",
        "TCMS_WRITE_BASE": "https://tcms.example/api/v1",
        "TCMS_USER": "u",
        "TCMS_PASSWORD": "p",
        "TESTCASE_MGMT_DATA_DIR": tempfile.mkdtemp(),
    }

    # Minimal deps used by helpers
    def _tcms_auth():
        return ("u", "p")

    ns["_tcms_auth"] = _tcms_auth

    # Provide load/save that write into temp dir (same helpers later in file — stub)
    store = {}

    def _tc_data_file(branch, team):
        return f"{branch}__{team}"

    def _load_tc_data(branch, team):
        key = _tc_data_file(branch, team)
        return store.get(key) or {
            "last_updated": None,
            "branch": branch,
            "team": team,
            "testcases": [],
        }

    def _save_tc_data(branch, team, data):
        store[_tc_data_file(branch, team)] = data

    ns["_tc_data_file"] = _tc_data_file
    ns["_load_tc_data"] = _load_tc_data
    ns["_save_tc_data"] = _save_tc_data
    ns["_STORE"] = store

    exec(chunk, ns)  # noqa: S102
    return ns


A = "aaaaaaaaaaaaaaaaaaaaaaaa"
B = "bbbbbbbbbbbbbbbbbbbbbbbb"
TCMS_A = "111111111111111111111111"
TCMS_B = "222222222222222222222222"


class TestTargetBranch(unittest.TestCase):
    def test_normalize_and_nutest_target(self):
        ns = _load_helpers()
        norm = ns["_normalize_tc_branch_key"]
        fn = ns["_tcms_nutest_target_branch"]
        self.assertEqual(norm("master"), "master")
        self.assertEqual(norm("7.6"), "7.6")
        self.assertEqual(norm("ganges-7.6-stable"), "7.6")
        self.assertEqual(norm("ganges-7.5-stable"), "7.5")
        self.assertEqual(norm("ganges-7.6.0.6-stable"), "7.6.0.6")
        self.assertEqual(norm("7.6.0.6"), "7.6.0.6")
        self.assertEqual(fn("master"), "master")
        self.assertEqual(fn("7.6"), "ganges-7.6-stable")
        self.assertEqual(fn("ganges-7.6-stable"), "ganges-7.6-stable")
        self.assertEqual(fn("7.5"), "ganges-7.5-stable")
        self.assertEqual(fn("7.6.0.6"), "ganges-7.6.0.6-stable")
        self.assertEqual(fn("ganges-7.6.0.6-stable"), "ganges-7.6.0.6-stable")
        cfg = ns["_resolve_branch_config"]
        ns["TESTCASE_MGMT_BRANCHES"] = {
            "master": {"milestone": "master", "team_prefix": "master", "test_set_regex": "test_sets/milestones/master/"},
            "ganges-7.6-stable": {"milestone": "7.6", "team_prefix": "7.6", "test_set_regex": "test_sets/milestones/7.6/"},
            "ganges-7.5-stable": {"milestone": "7.5", "team_prefix": "7.5", "test_set_regex": "test_sets/milestones/7.5/"},
        }
        self.assertEqual(cfg("ganges-7.6-stable")["milestone"], "7.6")
        self.assertEqual(cfg("ganges-7.6.0.6-stable")["milestone"], "7.6.0.6")
        self.assertEqual(cfg("7.6.0.6")["milestone"], "7.6.0.6")


class TestResolveTcmsMilestone(unittest.TestCase):
    def test_ganges_patch_and_release_versions(self):
        path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("BRANCH_SHORT_NAME_MAP = {")
        end = src.index("# AI Endpoint for failure summary")
        start_fn = src.index("def _resolve_tcms_milestone(")
        end_fn = src.index("@app.route(\"/mcp/regression/tcms-overall-qi\"")
        ns = {"re": __import__("re")}
        exec(src[start:end], ns)  # noqa: S102
        exec(src[start_fn:end_fn], ns)  # noqa: S102
        fn = ns["_resolve_tcms_milestone"]
        self.assertEqual(fn("ganges-7.6.0.6-stable"), "7.6.0.6")
        self.assertEqual(fn("ganges-7.6-stable"), "7.6")
        self.assertEqual(fn("ganges-7.5-stable"), "7.5")
        self.assertEqual(fn("ganges-7.5.1-stable"), "7.5.1")
        self.assertEqual(fn("master"), "master")
        self.assertEqual(fn("7.6.0.6"), "7.6.0.6")
        self.assertEqual(fn("ganges-7.3.0.98-stable"), "7.3.0.98")


class TestApplyTagOps(unittest.TestCase):
    def test_add_and_delete_single_and_multi(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        store = ns["_STORE"]
        store["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                {"oid": A, "name": "pkg.Test.a", "tags": [], "tcms_oid": TCMS_A},
                {"oid": B, "name": "pkg.Test.b", "tags": ["keep"], "tcms_oid": TCMS_B},
            ],
        }

        put_calls = []

        def fake_mutate(tcms_oid, tags, action="add"):
            put_calls.append((tcms_oid, list(tags), action))
            return True, 200, "ok"

        ns["_tcms_mutate_testcase_tags"] = fake_mutate
        ns["_resolve_tcms_all_testcase_oid"] = lambda name, branch: (
            TCMS_A if "a" in name else TCMS_B,
            list(next(
                (t.get("tags") or [] for t in store["master__CDP"]["testcases"] if t.get("name") == name),
                [],
            )),
        )
        r = apply([A], ["newtag"], "master", "CDP", action="add")
        self.assertEqual(r["success"], 1)
        self.assertEqual(r["failed"], 0)
        self.assertIn(A, r["updated_oids"])
        self.assertEqual(store["master__CDP"]["testcases"][0]["tags"], ["newtag"])

        r2 = apply([A, B], ["newtag"], "master", "CDP", action="add")
        self.assertEqual(r2["success"], 2)
        tags_b = store["master__CDP"]["testcases"][1]["tags"]
        self.assertIn("keep", tags_b)
        self.assertIn("newtag", tags_b)

        r3 = apply([A, B], ["newtag"], "master", "CDP", action="delete")
        self.assertEqual(r3["success"], 2)
        self.assertEqual(store["master__CDP"]["testcases"][0]["tags"], [])
        self.assertEqual(store["master__CDP"]["testcases"][1]["tags"], ["keep"])

        # Used correct tcms oids (not aggregate A/B) for mutations
        used = {c[0] for c in put_calls}
        self.assertEqual(used, {TCMS_A, TCMS_B})

    def test_missing_local_oid_reports_not_present(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [],
        }
        r = apply([A], ["x"], "master", "CDP", action="add")
        self.assertEqual(r["success"], 0)
        self.assertEqual(r["failed"], 1)
        self.assertIn("Not present", r["errors"][0]["error"])

    def test_resolves_tcms_oid_when_missing(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                {"oid": A, "name": "pkg.Test.a", "tags": [], "tcms_oid": ""},
            ],
        }

        def fake_resolve(name, branch):
            self.assertEqual(name, "pkg.Test.a")
            return TCMS_A, ["old"]

        def fake_mutate(tcms_oid, tags, action="add"):
            self.assertEqual(tcms_oid, TCMS_A)
            return True, 200, "ok"

        ns["_resolve_tcms_all_testcase_oid"] = fake_resolve
        ns["_tcms_mutate_testcase_tags"] = fake_mutate
        r = apply([A], ["t1"], "master", "CDP", action="add")
        self.assertEqual(r["success"], 1)
        self.assertEqual(ns["_STORE"]["master__CDP"]["testcases"][0]["tcms_oid"], TCMS_A)
        # Remote had ["old"]; add merges t1 without dropping existing remote tags
        self.assertEqual(ns["_STORE"]["master__CDP"]["testcases"][0]["tags"], ["old", "t1"])

    def test_failed_tcms_does_not_update_local_tags(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                {"oid": A, "name": "pkg.Test.a", "tags": ["keep"], "tcms_oid": TCMS_A},
            ],
        }
        ns["_tcms_mutate_testcase_tags"] = lambda *a, **k: (False, 404, "not found")
        ns["_resolve_tcms_all_testcase_oid"] = lambda *a, **k: (TCMS_A, ["keep"])
        r = apply([A], ["x"], "master", "CDP", action="add")
        self.assertEqual(r["success"], 0)
        self.assertEqual(ns["_STORE"]["master__CDP"]["testcases"][0]["tags"], ["keep"])

    def test_delete_missing_tag_says_not_present(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                {"oid": A, "name": "pkg.Test.a", "tags": ["keep"], "tcms_oid": TCMS_A},
            ],
        }
        mutate_calls = []

        def fake_mutate(tcms_oid, tags, action="add"):
            mutate_calls.append((tcms_oid, list(tags), action))
            return True, 200, "ok"

        ns["_tcms_mutate_testcase_tags"] = fake_mutate
        ns["_resolve_tcms_all_testcase_oid"] = lambda *a, **k: (TCMS_A, ["keep"])

        r = apply([A], ["nope"], "master", "CDP", action="delete")
        self.assertEqual(r["success"], 0)
        self.assertEqual(r["failed"], 1)
        self.assertTrue(r["errors"][0]["error"].startswith("Tag not present"))
        self.assertEqual(r.get("error"), "Tag not present: nope")
        self.assertEqual(mutate_calls, [])  # must not call TCMS delete
        self.assertEqual(ns["_STORE"]["master__CDP"]["testcases"][0]["tags"], ["keep"])

    def test_delete_only_removes_present_tags(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                {"oid": A, "name": "pkg.Test.a", "tags": ["keep", "gone"], "tcms_oid": TCMS_A},
            ],
        }
        mutate_calls = []

        def fake_mutate(tcms_oid, tags, action="add"):
            mutate_calls.append((list(tags), action))
            return True, 200, "ok"

        ns["_tcms_mutate_testcase_tags"] = fake_mutate
        ns["_resolve_tcms_all_testcase_oid"] = lambda *a, **k: (TCMS_A, ["keep", "gone"])

        r = apply([A], ["gone", "missing"], "master", "CDP", action="delete")
        self.assertEqual(r["success"], 1)
        self.assertEqual(mutate_calls, [(["gone"], "delete")])
        self.assertEqual(ns["_STORE"]["master__CDP"]["testcases"][0]["tags"], ["keep"])
        self.assertEqual(r["not_present"][0]["tags"], ["missing"])

    def test_add_already_present_is_noop_success(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                {"oid": A, "name": "pkg.Test.a", "tags": ["Keep"], "tcms_oid": TCMS_A},
            ],
        }
        mutate_calls = []

        def fake_mutate(tcms_oid, tags, action="add"):
            mutate_calls.append((list(tags), action))
            return True, 200, "ok"

        # Remote confirms same tag (case-insensitive)
        ns["_resolve_tcms_all_testcase_oid"] = lambda *a, **k: (TCMS_A, ["Keep"])
        ns["_tcms_mutate_testcase_tags"] = fake_mutate
        r = apply([A], ["keep"], "master", "CDP", action="add")
        self.assertEqual(r["success"], 1)
        self.assertEqual(mutate_calls, [])  # no TCMS add when already present
        self.assertEqual(ns["_STORE"]["master__CDP"]["testcases"][0]["tags"], ["Keep"])

    def test_add_case_insensitive_no_duplicate(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                {"oid": A, "name": "pkg.Test.a", "tags": ["Keep"], "tcms_oid": TCMS_A},
            ],
        }
        ns["_resolve_tcms_all_testcase_oid"] = lambda *a, **k: (TCMS_A, ["Keep"])
        ns["_tcms_mutate_testcase_tags"] = lambda *a, **k: (True, 200, "ok")
        r = apply([A], ["keep", "KEEP", "new"], "master", "CDP", action="add")
        self.assertEqual(r["success"], 1)
        tags = ns["_STORE"]["master__CDP"]["testcases"][0]["tags"]
        self.assertEqual(tags, ["Keep", "new"])

    def test_delete_resolve_fail_still_attempts_tcms(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                # Local cache empty tags (stale) but oid known
                {"oid": A, "name": "pkg.Test.a", "tags": [], "tcms_oid": TCMS_A},
            ],
        }
        mutate_calls = []

        def fake_mutate(tcms_oid, tags, action="add"):
            mutate_calls.append((tcms_oid, list(tags), action))
            return True, 200, "ok"

        ns["_resolve_tcms_all_testcase_oid"] = lambda *a, **k: (None, [])
        ns["_tcms_mutate_testcase_tags"] = fake_mutate
        r = apply([A], ["gone"], "master", "CDP", action="delete")
        self.assertEqual(r["success"], 1)
        self.assertEqual(mutate_calls, [(TCMS_A, ["gone"], "delete")])

    def test_stale_oid_404_retries_with_resolved(self):
        ns = _load_helpers()
        apply = ns["_apply_testcase_tag_ops"]
        stale = "deadbeefdeadbeefdeadbeef"
        ns["_STORE"]["master__CDP"] = {
            "branch": "master",
            "team": "CDP",
            "testcases": [
                {"oid": A, "name": "pkg.Test.a", "tags": [], "tcms_oid": stale},
            ],
        }
        calls = []
        resolve_n = {"n": 0}

        def fake_mutate(tcms_oid, tags, action="add"):
            calls.append(tcms_oid)
            if tcms_oid == stale:
                return False, 404, "not found"
            return True, 200, "ok"

        def fake_resolve(name, branch):
            # First resolve(s) still return stale; after 404 retry returns real oid
            resolve_n["n"] += 1
            if resolve_n["n"] <= 1:
                return stale, []
            return TCMS_A, []

        ns["_tcms_mutate_testcase_tags"] = fake_mutate
        ns["_resolve_tcms_all_testcase_oid"] = fake_resolve
        r = apply([A], ["x"], "master", "CDP", action="add")
        self.assertEqual(r["success"], 1)
        self.assertEqual(calls[0], stale)
        self.assertIn(TCMS_A, calls)
        self.assertEqual(ns["_STORE"]["master__CDP"]["testcases"][0]["tcms_oid"], TCMS_A)


class TestCacheLoadSave(unittest.TestCase):
    def test_newer_short_key_beats_richer_stale_legacy(self):
        """Tag delete saved to short key must not be undone by older rich legacy file."""
        import json
        from datetime import datetime, timedelta

        tmp = tempfile.mkdtemp()
        path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        # Extract normalize + candidate paths + load/save
        start = src.index("def _normalize_tc_branch_key(")
        end = src.index("def _resolve_branch_config(")
        chunk1 = src[start:end]
        start2 = src.index("def _tc_data_file(")
        end2 = src.index("@app.route(\"/mcp/regression/testcase-mgmt/fetch-data\"")
        chunk2 = src[start2:end2]
        ns = {
            "os": os,
            "re": __import__("re"),
            "json": json,
            "datetime": datetime,
            "logger": __import__("types").SimpleNamespace(
                info=lambda *a, **k: None,
                warning=lambda *a, **k: None,
            ),
            "TESTCASE_MGMT_DATA_DIR": tmp,
            "_DOTTED_VERSION_RE": __import__("re").compile(r"\d+(?:\.\d+)+"),
        }
        exec(chunk1, ns)  # noqa: S102
        exec(chunk2, ns)  # noqa: S102

        legacy = os.path.join(tmp, "testcase_management_ganges-7.6-stable_CDP.json")
        short = os.path.join(tmp, "testcase_management_7.6_CDP.json")
        old = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
        new = datetime.utcnow().isoformat() + "Z"
        # Legacy: richer tags but older
        with open(legacy, "w") as f:
            json.dump({
                "last_updated": old,
                "branch": "7.6",
                "team": "CDP",
                "testcases": [
                    {"oid": A, "name": "a", "tags": ["stale1", "stale2"], "tcms_oid": TCMS_A},
                    {"oid": B, "name": "b", "tags": ["stale3"], "tcms_oid": TCMS_B},
                ],
            }, f)
        # Short: fewer tags (after delete) but newer
        with open(short, "w") as f:
            json.dump({
                "last_updated": new,
                "branch": "7.6",
                "team": "CDP",
                "testcases": [
                    {"oid": A, "name": "a", "tags": [], "tcms_oid": TCMS_A},
                    {"oid": B, "name": "b", "tags": [], "tcms_oid": TCMS_B},
                ],
            }, f)

        data = ns["_load_tc_data"]("7.6", "CDP")
        self.assertEqual(data["testcases"][0]["tags"], [])
        self.assertEqual(data["testcases"][1]["tags"], [])

        # Save must write both candidate paths
        data["testcases"][0]["tags"] = ["fresh"]
        data["last_updated"] = datetime.utcnow().isoformat() + "Z"
        ns["_save_tc_data"]("7.6", "CDP", data)
        with open(legacy) as f:
            legacy_data = json.load(f)
        self.assertEqual(legacy_data["testcases"][0]["tags"], ["fresh"])


if __name__ == "__main__":
    unittest.main()
