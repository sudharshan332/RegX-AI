"""Failed-analysis status matching must not drop skipped/pending task-id results."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_flask import _count_test_statuses, _normalize_test_status  # noqa: E402


class TestNormalizeTestStatus(unittest.TestCase):
    def test_string_and_none(self):
        self.assertEqual(_normalize_test_status("Failed"), "failed")
        self.assertEqual(_normalize_test_status(" Pending "), "pending")
        self.assertEqual(_normalize_test_status(None), "")
        self.assertEqual(_normalize_test_status({"name": "Skipped"}), "skipped")

    def test_count_and_filter(self):
        rows = [
            {"status": "Skipped"},
            {"status": "Skipped"},
            {"status": "Pending"},
            {"status": "Failed"},
        ]
        counts = _count_test_statuses(rows)
        self.assertEqual(counts, {"skipped": 2, "pending": 1, "failed": 1})
        matched = [r for r in rows if _normalize_test_status(r.get("status")) in {"failed", "failure"}]
        self.assertEqual(len(matched), 1)
        skipped = [r for r in rows if _normalize_test_status(r.get("status")) in {"skipped", "skip"}]
        self.assertEqual(len(skipped), 2)


if __name__ == "__main__":
    unittest.main()
