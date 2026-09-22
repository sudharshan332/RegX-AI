"""Unit tests for handover last-5 JITA lookup by test name."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handover_helpers import AmbiguousTestNameError  # noqa: E402


def _row(name, branch, start_time, status="Succeeded", tid="t0"):
    return {
        "test": {"name": name},
        "system_under_test": {"branch": branch},
        "start_time": start_time,
        "status": status,
        "jira_tickets": [],
        "agave_task_id": {"$oid": tid},
    }


class FetchHandoverRunsForTestNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("FLASK_ENV", "testing")
        try:
            import test_flask as tf
            cls.tf = tf
        except Exception as exc:
            raise unittest.SkipTest("test_flask import failed: %s" % exc) from exc

    def _patch_query(self, fake):
        orig = self.tf._query_jita_agave_test_results
        self.tf._query_jita_agave_test_results = fake
        return orig

    def test_exact_match_keeps_last_5(self):
        def fake_query(raw_query, limit=50, sort_field="-start_time", timeout=90):
            name = raw_query.get("test.name")
            if name != "cdp.foo.test_a":
                return []
            return [
                _row("cdp.foo.test_a", "master", "2026-09-%02d" % (10 - i), tid="t%d" % i)
                for i in range(6)
            ]

        orig = self._patch_query(fake_query)
        try:
            resolved, runs = self.tf._fetch_handover_runs_for_test_name(
                "cdp.foo.test_a", "master", limit=5
            )
        finally:
            self.tf._query_jita_agave_test_results = orig
        self.assertEqual(resolved, "cdp.foo.test_a")
        self.assertEqual(len(runs), 5)
        self.assertEqual([r["agave_task_id"]["$oid"] for r in runs], ["t0", "t1", "t2", "t3", "t4"])
        self.assertNotIn("t5", [r["agave_task_id"]["$oid"] for r in runs])

    def test_regex_suffix_when_exact_misses(self):
        full = "cdp.foo.MyTest.test_basic"

        def fake_query(raw_query, limit=50, sort_field="-start_time", timeout=90):
            name = raw_query.get("test.name")
            if isinstance(name, str):
                return []
            return [
                _row(full, "master", "2026-09-10", tid="t1"),
                _row(full, "ganges-7.6-stable", "2026-09-09", tid="t2"),
            ]

        orig = self._patch_query(fake_query)
        try:
            resolved, runs = self.tf._fetch_handover_runs_for_test_name(
                "test_basic", "master", limit=5
            )
        finally:
            self.tf._query_jita_agave_test_results = orig
        self.assertEqual(resolved, full)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["agave_task_id"]["$oid"], "t1")

    def test_ambiguous_raises(self):
        def fake_query(raw_query, limit=50, sort_field="-start_time", timeout=90):
            name = raw_query.get("test.name")
            if isinstance(name, str):
                return []
            return [
                _row("pkg.A.test_foo", "master", "2026-09-10", tid="t1"),
                _row("pkg.B.test_foo", "master", "2026-09-09", tid="t2"),
            ]

        orig = self._patch_query(fake_query)
        try:
            with self.assertRaises(AmbiguousTestNameError) as ctx:
                self.tf._fetch_handover_runs_for_test_name("test_foo", "master", limit=5)
            self.assertEqual(ctx.exception.candidates, ["pkg.A.test_foo", "pkg.B.test_foo"])
        finally:
            self.tf._query_jita_agave_test_results = orig

    def test_zero_hits_returns_empty(self):
        orig = self._patch_query(lambda *args, **kwargs: [])
        try:
            resolved, runs = self.tf._fetch_handover_runs_for_test_name(
                "missing.test", "master", limit=5
            )
        finally:
            self.tf._query_jita_agave_test_results = orig
        self.assertEqual(resolved, "missing.test")
        self.assertEqual(runs, [])


if __name__ == "__main__":
    unittest.main()
