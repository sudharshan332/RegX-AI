"""Unit tests for run-plan job profile id normalization."""

import os
import unittest


def _load_helper():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _normalize_run_plan_jp_ids(")
    end = src.index('@app.route("/mcp/regression/run-plan/<run_plan_id>", methods=["PUT"]')
    ns = {}
    exec(src[start:end], ns)  # noqa: S102
    return ns


class TestNormalizeRunPlanJpIds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helper()

    def _norm(self, raw):
        return self.ns["_normalize_run_plan_jp_ids"](raw)

    def test_strips_and_dedupes_strings(self):
        self.assertEqual(
            self._norm(["  a  ", "b", "a", "", None]),
            ["a", "b"],
        )

    def test_unwraps_oid_objects(self):
        self.assertEqual(
            self._norm([{"$oid": "6a7c7400d24d8207efaa4581"}, {"_id": {"$oid": "abc"}}]),
            ["6a7c7400d24d8207efaa4581", "abc"],
        )

    def test_empty_input(self):
        self.assertEqual(self._norm(None), [])
        self.assertEqual(self._norm([]), [])


if __name__ == "__main__":
    unittest.main()
