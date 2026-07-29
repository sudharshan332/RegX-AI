"""Unit tests for Triage Genie coverage rollup + cache match (no JITA/TG network)."""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    # Fingerprint + cache match + rollup + TG link helpers (no Flask app import)
    start = src.index("def _sorted_task_id_fingerprint(")
    end = src.index("def _resolve_triage_scope_from_request(")
    chunk = src[start:end]

    # Stub extras / jobs loaders used by extracted helpers
    def get_extras_for_tag(config, tag):
        return (config or {}).get("extras", {}).get(tag, [])

    def load_regression_config():
        return {"extras": {}}

    def load_triage_genie_jobs():
        return {"jobs": _load_helpers._jobs}

    ns = {
        "datetime": datetime,
        "get_extras_for_tag": get_extras_for_tag,
        "load_regression_config": load_regression_config,
        "load_triage_genie_jobs": load_triage_genie_jobs,
    }
    exec(chunk, ns)  # noqa: S102
    return ns


_load_helpers._jobs = []
_H = _load_helpers()
_ROLLUP = _H["_rollup_triage_genie_coverage"]
_MATCH = _H["_config_matches_cached"]
_FIND = _H["_find_best_triage_genie_job"]
_TG_URL = _H["_build_triage_genie_job_url"]


class TestTriageGenieCoverageRollup(unittest.TestCase):
    def test_rollup_summary_and_owner_sort(self):
        payload = {
            "generated_time": "2026-07-24T00:00:00",
            "tag": "7.6.0.6",
            "task_ids": ["aaa", "bbb"],
            "testcases": [
                {
                    "testcase_name": "a.TestA",
                    "regression_owner": "alice",
                    "triage_genie_ticket": "ENG-1",
                    "jira_ticket": "ENG-1",
                },
                {
                    "testcase_name": "b.TestB",
                    "regression_owner": "bob",
                    "triage_genie_ticket": "",
                    "jira_ticket": "ENG-2",
                },
                {
                    "testcase_name": "c.TestC",
                    "regression_owner": "bob",
                    "triage_genie_ticket": "",
                    "jira_ticket": "",
                },
                {
                    "testcase_name": "d.TestD",
                    "regression_owner": "alice",
                    "triage_genie_ticket": "",
                    "jira_ticket": "ENG-3",
                },
            ],
        }
        out = _ROLLUP(payload)
        self.assertEqual(out["tag"], "7.6.0.6")
        self.assertEqual(
            out["summary"],
            {
                "total": 4,
                "via_triage_genie": 1,
                "jira_tagged": 3,
                "remaining_need_tg": 3,
                "manual_only": 2,
                "pct_tg": 25.0,
            },
        )
        self.assertEqual([r["owner"] for r in out["by_owner"]], ["bob", "alice"])
        self.assertIn("task_ids=aaa,bbb", out["links"]["jita_results_url"] or "")
        # Primary Open TG link = JITA "View in Triage Genie" style
        self.assertEqual(
            out["links"]["triage_genie_url"],
            "http://triage-genie.eng.nutanix.com/?jita_task_ids=aaa,bbb",
        )
        self.assertEqual(
            out["links"]["triage_genie_view_url"],
            "http://triage-genie.eng.nutanix.com/?jita_task_ids=aaa,bbb",
        )

    def test_cache_miss_when_full_link_grows(self):
        cached = {
            "tag": "7.6|RC1",
            "task_ids": ["aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"],
            "tag_extra_task_ids": [],
        }
        # Same tag, larger Full regression link → must NOT reuse cache
        full = cached["task_ids"] + ["cccccccccccccccccccccccc"]
        self.assertFalse(_MATCH(cached, "7.6|RC1", full))
        # Identical Full link → hit
        self.assertTrue(_MATCH(cached, "7.6|RC1", list(cached["task_ids"])))

    def test_cache_miss_when_extras_change_tag_only(self):
        cached = {
            "tag": "7.6|RC1",
            "task_ids": ["aaaaaaaaaaaaaaaaaaaaaaaa"],
            "tag_extra_task_ids": [],
        }
        # Tag-only with empty extras matches
        self.assertTrue(_MATCH(cached, "7.6|RC1", None))

        # Patch loader extras via re-exec with custom config — use direct fingerprint path:
        # inject by temporarily replacing loaders on helper ns
        def load_cfg():
            return {"extras": {"7.6|RC1": ["dddddddddddddddddddddddd"]}}

        def get_ex(cfg, tag):
            return (cfg or {}).get("extras", {}).get(tag, [])

        path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("def _sorted_task_id_fingerprint(")
        end = src.index("def _empty_triage_accuracy_payload(")
        ns = {
            "datetime": datetime,
            "get_extras_for_tag": get_ex,
            "load_regression_config": load_cfg,
        }
        exec(src[start:end], ns)  # noqa: S102
        self.assertFalse(ns["_config_matches_cached"](cached, "7.6|RC1", None))

    def test_tg_url_always_view_in_tg_even_on_exact_job(self):
        """Open link is always JITA View-in-TG (?jita_task_ids=); job id is metadata only."""
        _load_helpers._jobs = [
            {
                "id": 42,
                "name": "Reg_7.6",
                "jita_task_id_list": ["aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"],
            }
        ]
        h = _load_helpers()
        wanted = ["aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"]
        job = h["_find_best_triage_genie_job"](wanted)
        self.assertEqual(job["id"], 42)
        links = h["_build_triage_genie_job_url"](wanted, tag="7.6")
        expected = "http://triage-genie.eng.nutanix.com/?jita_task_ids=" + ",".join(wanted)
        self.assertEqual(links["triage_genie_url"], expected)
        self.assertEqual(links["triage_genie_view_url"], expected)
        self.assertEqual(links["triage_genie_job_id"], 42)

    def test_tg_job_rejects_weak_overlap_uses_view_in_tg_url(self):
        """Weak overlap must NOT deep-link; use View-in-TG jita_task_ids URL."""
        _load_helpers._jobs = [
            {
                "id": 3192,
                "name": "Other_Job",
                "jita_task_id_list": ["aaaaaaaaaaaaaaaaaaaaaaaa"],
            }
        ]
        h = _load_helpers()
        wanted = [
            "aaaaaaaaaaaaaaaaaaaaaaaa",
            "bbbbbbbbbbbbbbbbbbbbbbbb",
            "cccccccccccccccccccccccc",
            "dddddddddddddddddddddddd",
        ]
        self.assertIsNone(h["_find_best_triage_genie_job"](wanted))
        links = h["_build_triage_genie_job_url"](wanted, tag="7.6|RC1")
        self.assertEqual(
            links["triage_genie_url"],
            "http://triage-genie.eng.nutanix.com/?jita_task_ids=" + ",".join(wanted),
        )
        self.assertNotIn("/tasks/3192", links["triage_genie_url"] or "")
        self.assertEqual(links["triage_genie_view_url"], links["triage_genie_url"])

    def test_strong_overlap_non_exact_uses_view_in_tg_url(self):
        """Majority overlap without exact match → View-in-TG URL, not /tasks/{id}."""
        _load_helpers._jobs = [
            {
                "id": 99,
                "name": "Almost",
                "jita_task_id_list": [
                    "aaaaaaaaaaaaaaaaaaaaaaaa",
                    "bbbbbbbbbbbbbbbbbbbbbbbb",
                    "cccccccccccccccccccccccc",
                ],
            }
        ]
        h = _load_helpers()
        wanted = [
            "aaaaaaaaaaaaaaaaaaaaaaaa",
            "bbbbbbbbbbbbbbbbbbbbbbbb",
            "cccccccccccccccccccccccc",
            "dddddddddddddddddddddddd",
        ]
        links = h["_build_triage_genie_job_url"](wanted, tag="7.6|RC1")
        self.assertIn("jita_task_ids=", links["triage_genie_url"] or "")
        self.assertNotIn("/tasks/99", links["triage_genie_url"] or "")


if __name__ == "__main__":
    unittest.main()
