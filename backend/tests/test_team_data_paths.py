"""Team-scoped data/{TEAM}/ path helpers."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_path_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _get_legacy_data_dir(")
    end = src.index("def _get_run_plans_storage_path(")
    ns = {
        "os": os,
        "get_default_team": lambda: "CDP_FT",
    }
    exec(src[start:end], ns)  # noqa: S102
    return ns


class TestTeamDataPaths(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.ns = _load_path_helpers()
        self.ns["_get_legacy_data_dir"] = lambda: self.root
        self._prev_override = os.environ.pop("REGX_TEAM_DATA_DIR", None)

    def tearDown(self):
        if self._prev_override is None:
            os.environ.pop("REGX_TEAM_DATA_DIR", None)
        else:
            os.environ["REGX_TEAM_DATA_DIR"] = self._prev_override

    def test_write_goes_to_current_team_dir(self):
        self.ns["_get_current_team"] = lambda: "CDP_ST"
        path = self.ns["_resolve_team_or_legacy_file"](
            "failed_analysis_saved_tags.json", for_write=True
        )
        expected = os.path.join(self.root, "CDP_ST", "failed_analysis_saved_tags.json")
        self.assertEqual(path, expected)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "CDP_ST")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "CDP_FT")))

    def test_read_falls_back_to_flat_data(self):
        legacy = os.path.join(self.root, "handover_records.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.ns["_get_current_team"] = lambda: "CDP_ST"
        path = self.ns["_resolve_team_or_legacy_file"](
            "handover_records.json", for_write=False
        )
        self.assertEqual(path, legacy)

    def test_read_prefers_team_file_over_legacy(self):
        team_dir = os.path.join(self.root, "CDP_ST")
        os.makedirs(team_dir, exist_ok=True)
        team_file = os.path.join(team_dir, "handover_records.json")
        with open(team_file, "w", encoding="utf-8") as fh:
            fh.write("{}")
        with open(os.path.join(self.root, "handover_records.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.ns["_get_current_team"] = lambda: "CDP_ST"
        path = self.ns["_resolve_team_or_legacy_file"](
            "handover_records.json", for_write=False
        )
        self.assertEqual(path, team_file)


if __name__ == "__main__":
    unittest.main()
