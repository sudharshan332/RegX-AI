"""Ensure large task_id lists are fetched in batches (no single mega GET → 414)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_fetch_raw():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("# JITA GET /tasks?raw_query=")
    end = src.index("def fetch_regression_tasks(")
    chunk = src[start:end]

    calls = []

    class FakeResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": self._data}

    def fake_get(url, params=None, timeout=None):
        import json as _json

        rq = _json.loads(params["raw_query"])
        oids = [x["$oid"] for x in rq["_id"]["$in"]]
        calls.append(oids)
        # URL-length guard: batch must stay small
        assert len(oids) <= 40, f"batch too large: {len(oids)}"
        return FakeResp(
            [{"_id": {"$oid": oid}, "label": oid} for oid in oids]
        )

    ns = {
        "json": __import__("json"),
        "session": mock.Mock(get=fake_get),
        "JITA_BASE": "https://jita.example/api/v2",
        "logger": mock.Mock(),
        "requests": mock.Mock(exceptions=mock.Mock(
            ConnectionError=ConnectionError,
            Timeout=TimeoutError,
            RequestException=Exception,
        )),
    }
    exec(chunk, ns)  # noqa: S102
    return ns["_fetch_regression_tasks_raw"], calls


class TestFetchTasksBatch(unittest.TestCase):
    def test_batches_large_id_list(self):
        fetch_raw, calls = _load_fetch_raw()
        ids = [f"{i:024x}" for i in range(95)]
        out = fetch_raw(task_ids=ids)
        self.assertEqual(len(out), 95)
        self.assertEqual(len(calls), 3)  # 40 + 40 + 15
        self.assertEqual(len(calls[0]), 40)
        self.assertEqual(len(calls[1]), 40)
        self.assertEqual(len(calls[2]), 15)


def _load_tag_query():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("_DIRECT_JITA_REGRESSION_CREATORS = (")
    end = src.index("def _fetch_regression_tasks_raw(")
    ns = {
        "CDP_REG_JARVIS_MEMBERS": {
            "shilpa.sattigeri",
            "sudharshan.musali",
            "thanuja.c",
            "swapnil.wankhede",
        },
        "CDP_REG_JARVIS_GROUP": "cdp_reg_jarvis",
    }
    exec(src[start:end], ns)  # noqa: S102
    return ns["_regression_tag_raw_query"]


class TestRegressionTagQuery(unittest.TestCase):
    def test_includes_direct_jita_creator_with_tag(self):
        raw_query = _load_tag_query()("7.6.1_RC")
        creators = raw_query["$or"][0]["created_by"]["$in"]
        self.assertIn("suryaprabha.k", creators)
        self.assertIn("shilpa.sattigeri", creators)
        self.assertEqual(raw_query["tester_tags"], {"$in": ["7.6.1_RC"]})
        self.assertEqual(raw_query["system_under_test.component"], "main")
        self.assertEqual(
            raw_query["$or"][1],
            {"user_groups": {"$in": ["cdp_reg_jarvis"]}},
        )


if __name__ == "__main__":
    unittest.main()
