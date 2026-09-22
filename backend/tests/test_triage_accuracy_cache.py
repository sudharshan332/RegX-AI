"""Unit tests for triage-accuracy cache matching (no JITA/TG network)."""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_cache_helpers(load_regression_config=None, get_extras_for_tag=None):
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    start = src.index("def _sorted_task_id_fingerprint(")
    end = src.index("def _empty_triage_accuracy_payload(")
    chunk = src[start:end]

    def _default_extras(config, tag):
        return (config or {}).get("extras", {}).get(tag, [])

    def _default_config():
        return {"extras": {}}

    ns = {
        "datetime": datetime,
        "get_extras_for_tag": get_extras_for_tag or _default_extras,
        "load_regression_config": load_regression_config or _default_config,
    }
    exec(chunk, ns)  # noqa: S102
    return ns


_H = _load_cache_helpers()
_MATCH = _H["_config_matches_cached"]


class TestTriageAccuracyCache(unittest.TestCase):
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

        def load_cfg():
            return {"extras": {"7.6|RC1": ["dddddddddddddddddddddddd"]}}

        def get_ex(cfg, tag):
            return (cfg or {}).get("extras", {}).get(tag, [])

        ns = _load_cache_helpers(load_regression_config=load_cfg, get_extras_for_tag=get_ex)
        self.assertFalse(ns["_config_matches_cached"](cached, "7.6|RC1", None))


if __name__ == "__main__":
    unittest.main()
