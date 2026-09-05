"""Regression tests for owner triage aggregation — guard against false counts."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from owner_triage_report import (  # noqa: E402
    build_owner_status_table,
    extract_task_ids_from_execution_url,
    is_untriaged,
    normalize_task_ids,
    resolve_task_ids_from_payload,
)


class TestNormalizeTaskIds(unittest.TestCase):
    def test_dedupe_and_lowercase(self):
        valid, invalid = normalize_task_ids([
            "AAAAAAAAAAAAAAAAAAAAAAAA",
            "aaaaaaaaaaaaaaaaaaaaaaaa",
            "bbbbbbbbbbbbbbbbbbbbbbbb",
            "not-valid",
        ])
        self.assertEqual(valid, ["aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"])
        self.assertEqual(invalid, ["not-valid"])

    def test_url_extract_only_task_ids_param(self):
        a = "aaaaaaaaaaaaaaaaaaaaaaaa"
        b = "bbbbbbbbbbbbbbbbbbbbbbbb"
        c = "cccccccccccccccccccccccc"
        url = (
            f"https://jita.eng.nutanix.com/results?task_ids={a},{b}"
            f"&active_tab=1&merge_tests=true&x={c}"
        )
        ids = extract_task_ids_from_execution_url(url)
        self.assertEqual(ids, [a, b])
        self.assertNotIn(c, ids)


class TestUntriagedRules(unittest.TestCase):
    def test_failed_empty_jira(self):
        self.assertTrue(is_untriaged({
            "status": "Failed", "jira_tickets": [], "comments": ""
        }))

    def test_failed_with_jira_is_triaged(self):
        self.assertFalse(is_untriaged({
            "status": "Failed", "jira_tickets": ["ENG-1"], "comments": ""
        }))

    def test_test_passed_comment_excluded(self):
        self.assertFalse(is_untriaged({
            "status": "Skipped", "jira_tickets": [], "comments": "{ Test Passed }"
        }))

    def test_succeeded_never_untriaged(self):
        self.assertFalse(is_untriaged({
            "status": "Succeeded", "jira_tickets": [], "comments": ""
        }))


class TestAggregationAccuracy(unittest.TestCase):
    def test_schema_and_counts(self):
        records = [
            {"test": {"name": "cassandra.a"}, "status": "Failed", "jira_tickets": [], "comments": ""},
            {"test": {"name": "cassandra.b"}, "status": "Failed", "jira_tickets": ["ENG-1"], "comments": ""},
            {"test": {"name": "cassandra.c"}, "status": "Skipped", "jira_tickets": [], "comments": ""},
            {"test": {"name": "cassandra.d"}, "status": "Warning", "jira_tickets": [], "comments": "{Test Passed}"},
            {"test": {"name": "cassandra.e"}, "status": "Killed", "jira_tickets": [], "comments": ""},
            {"test": {"name": "cassandra.a"}, "status": "Failed", "jira_tickets": ["ENG-DUP"], "comments": ""},  # dupe name ignored
            {"test": {"name": "other.x"}, "status": "Failed", "jira_tickets": [], "comments": ""},
        ]

        def owner(name):
            return "Swapnil" if name.startswith("cassandra") else "Unmapped"

        out = build_owner_status_table(records, owner)
        keys = {
            "Regression_owner", "Total", "Total untriaged",
            "Failed", "Skipped", "Warning", "Killed",
        }
        for row in out["rows"]:
            self.assertEqual(set(row.keys()), keys)

        by_owner = {r["Regression_owner"]: r for r in out["rows"]}
        sw = by_owner["Swapnil"]
        # bad statuses: a Failed, b Failed, c Skipped, d Warning, e Killed = 5
        # (dupe name cassandra.a ignored — first wins: untriaged Failed)
        self.assertEqual(sw["Total"], 5)
        # untriaged: a Failed, c Skipped, e Killed (b has jira, d has Test Passed)
        self.assertEqual(sw["Total untriaged"], 3)
        self.assertEqual(sw["Failed"], 1)
        self.assertEqual(sw["Skipped"], 1)
        self.assertEqual(sw["Warning"], 0)
        self.assertEqual(sw["Killed"], 1)

        um = by_owner["Unmapped"]
        self.assertEqual(um["Total"], 1)
        self.assertEqual(um["Total untriaged"], 1)
        self.assertEqual(out["meta"]["total_untriaged"], 4)

        # Status columns sum must equal Total untriaged per owner
        for r in out["rows"]:
            self.assertEqual(
                r["Failed"] + r["Skipped"] + r["Warning"] + r["Killed"],
                r["Total untriaged"],
                msg=r,
            )

    def test_resolve_payload_prefers_task_ids(self):
        ids, inv, err, src = resolve_task_ids_from_payload(
            task_ids=["aaaaaaaaaaaaaaaaaaaaaaaa"],
            execution_url="https://jita.eng.nutanix.com/results?task_ids=bbbbbbbbbbbbbbbbbbbbbbbb",
        )
        self.assertEqual(src, "task_ids")
        self.assertEqual(ids, ["aaaaaaaaaaaaaaaaaaaaaaaa"])
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
