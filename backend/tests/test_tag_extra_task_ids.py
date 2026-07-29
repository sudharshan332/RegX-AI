"""Regression tests: per-tag extra task IDs must persist and merge uniquely."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tag_extra_task_ids import (  # noqa: E402
    append_extras_for_tag,
    classify_task_ids_against_tag,
    get_extras_for_tag,
    merge_unique_ids,
    normalize_task_id_list,
    plan_accept_after_tagging,
    remove_extras_for_tag,
    task_has_tag,
)


A = "aaaaaaaaaaaaaaaaaaaaaaaa"
B = "bbbbbbbbbbbbbbbbbbbbbbbb"
C = "cccccccccccccccccccccccc"
A_UP = "AAAAAAAAAAAAAAAAAAAAAAAA"


class TestNormalizeAndMerge(unittest.TestCase):
    def test_normalize_dedupe_case(self):
        self.assertEqual(
            normalize_task_id_list([A_UP, A, B, "bad"]),
            [A, B],
        )

    def test_merge_unique(self):
        self.assertEqual(merge_unique_ids([A, B], [B, C]), [A, B, C])


class TestAppendExtrasForTag(unittest.TestCase):
    def test_append_and_idempotent(self):
        config = {"tag_extra_task_ids": {}}
        updated, merged, newly = append_extras_for_tag(config, "tag-1", [A, B])
        self.assertEqual(newly, [A, B])
        self.assertEqual(merged, [A, B])
        self.assertEqual(get_extras_for_tag(updated, "tag-1"), [A, B])

        updated2, merged2, newly2 = append_extras_for_tag(updated, "tag-1", [B, C, A_UP])
        self.assertEqual(newly2, [C])  # B and A already present
        self.assertEqual(merged2, [A, B, C])
        # Other tags untouched
        self.assertEqual(get_extras_for_tag(updated2, "other"), [])

    def test_requires_tag_and_valid_ids(self):
        with self.assertRaises(ValueError):
            append_extras_for_tag({}, "", [A])
        with self.assertRaises(ValueError):
            append_extras_for_tag({}, "tag-1", ["not-an-id"])


class TestRemoveExtrasForTag(unittest.TestCase):
    def test_remove_and_clear_key(self):
        config = {"tag_extra_task_ids": {}}
        updated, _, _ = append_extras_for_tag(config, "tag-1", [A, B, C])
        updated2, remaining, removed = remove_extras_for_tag(updated, "tag-1", [B, A_UP])
        self.assertEqual(sorted(removed), sorted([A, B]))
        self.assertEqual(remaining, [C])
        self.assertEqual(get_extras_for_tag(updated2, "tag-1"), [C])

        updated3, remaining3, removed3 = remove_extras_for_tag(updated2, "tag-1", [C])
        self.assertEqual(removed3, [C])
        self.assertEqual(remaining3, [])
        self.assertNotIn("tag-1", updated3.get("tag_extra_task_ids") or {})

    def test_remove_unknown_is_noop_list(self):
        config = {"tag_extra_task_ids": {"tag-1": [A]}}
        updated, remaining, removed = remove_extras_for_tag(config, "tag-1", [B])
        self.assertEqual(removed, [])
        self.assertEqual(remaining, [A])
        self.assertEqual(get_extras_for_tag(updated, "tag-1"), [A])


class TestFetchMergesExtras(unittest.TestCase):
    """Unit-test merge behavior used by fetch_regression_tasks (no live JITA)."""

    def test_missing_extras_are_identifiable(self):
        tag_tasks = [
            {"_id": {"$oid": A}, "branch": "x"},
            {"_id": {"$oid": B}, "branch": "x"},
        ]
        extras = [A, C]
        found = {t["_id"]["$oid"] for t in tag_tasks}
        missing = [tid for tid in extras if tid not in found]
        self.assertEqual(missing, [C])

        extra_tasks = [{"_id": {"$oid": C}, "branch": "y"}]
        merged = []
        seen = set()
        for t in tag_tasks + extra_tasks:
            oid = t["_id"]["$oid"]
            if oid in seen:
                continue
            seen.add(oid)
            merged.append(oid)
        self.assertEqual(merged, [A, B, C])


class TestTagValidation(unittest.TestCase):
    def test_task_has_tag(self):
        self.assertTrue(task_has_tag(["7.6|RC3-july-13-2026", "other"], "7.6|RC3-july-13-2026"))
        self.assertFalse(task_has_tag(["other"], "7.6|RC3-july-13-2026"))
        self.assertFalse(task_has_tag(None, "7.6|RC3-july-13-2026"))
        self.assertFalse(task_has_tag("not-a-list", "7.6|RC3-july-13-2026"))

    def test_classify_matched_wrong_not_found(self):
        tag = "my-tag"
        meta = {
            A: {"tester_tags": [tag, "x"]},
            B: {"tester_tags": ["other-tag"]},
            # C missing → not_found
        }
        result = classify_task_ids_against_tag([A, B, C, A_UP], tag, meta)
        self.assertEqual(result["matched"], [A])  # A_UP normalizes to A, already counted once in input normalize
        # Input [A, B, C, A_UP] → normalize unique → [A, B, C]
        self.assertEqual(result["wrong_tag"], [B])
        self.assertEqual(result["not_found"], [C])

    def test_only_matched_are_safe_to_persist(self):
        tag = "my-tag"
        meta = {
            A: {"tester_tags": [tag]},
            B: {"tester_tags": []},
        }
        result = classify_task_ids_against_tag([A, B], tag, meta)
        config = {"tag_extra_task_ids": {}}
        updated, merged, newly = append_extras_for_tag(config, tag, result["matched"])
        self.assertEqual(newly, [A])
        self.assertEqual(merged, [A])
        self.assertNotIn(B, get_extras_for_tag(updated, tag))

    def test_plan_accept_after_tagging_adds_wrong_tag_when_tagged(self):
        tag = "my-tag"
        classification = {
            "matched": [A],
            "wrong_tag": [B, C],
            "not_found": ["dddddddddddddddddddddddd"],
        }
        planned = plan_accept_after_tagging(
            classification,
            successfully_tagged=[B],
            failed_to_tag=[C],
        )
        self.assertEqual(planned["accepted"], [A, B])
        self.assertEqual(planned["tagged_now"], [B])
        self.assertEqual(planned["rejected_tag_failed"], [C])
        self.assertEqual(planned["rejected_not_found"], ["dddddddddddddddddddddddd"])

        # Persist only accepted
        config = {"tag_extra_task_ids": {}}
        updated, merged, newly = append_extras_for_tag(config, tag, planned["accepted"])
        self.assertEqual(set(newly), {A, B})
        self.assertNotIn(C, get_extras_for_tag(updated, tag))


class TestConfigRoundTrip(unittest.TestCase):
    def test_save_load_preserves_extras(self):
        # Simulate append → save → load without touching real regression_config.json
        config = {
            "input_mode": "tag",
            "default_tag": "my-tag",
            "added_tags": ["my-tag"],
            "tag": "my-tag",
            "task_ids": [],
            "tag_extra_task_ids": {},
        }
        updated, merged, newly = append_extras_for_tag(config, "my-tag", [A, B])
        self.assertEqual(newly, [A, B])

        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as fh:
            path = fh.name
        try:
            import json
            with open(path, "w") as f:
                json.dump(updated, f)
            with open(path, "r") as f:
                loaded = json.load(f)
            self.assertEqual(get_extras_for_tag(loaded, "my-tag"), [A, B])
        finally:
            os.unlink(path)


class TestAddTesterTagPutContract(unittest.TestCase):
    """JITA AgaveTask update must PUT only tester_tags (full-doc PUT fails)."""

    def test_put_payload_is_tags_only(self):
        import importlib.util
        from types import SimpleNamespace
        from unittest import mock

        # Load helper source without importing full Flask app
        path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("def _add_tester_tag_to_task(")
        end = src.index("\ndef _ensure_tester_tag_on_tasks(")
        ns = {
            "requests": __import__("requests"),
            "logger": SimpleNamespace(error=lambda *a, **k: None),
            "JITA_BASE": "https://jita.example/api/v2",
            "JITA_SVC_AUTH": ("u", "p"),
        }
        exec(src[start:end], ns)  # noqa: S102 — test isolation
        fn = ns["_add_tester_tag_to_task"]

        class FakeResp:
            def __init__(self, status, payload):
                self.status_code = status
                self._payload = payload
                self.content = b"{}"
                self.text = str(payload)

            def json(self):
                return self._payload

        put_bodies = []
        get_calls = {"n": 0}

        def fake_get(url, **kwargs):
            get_calls["n"] += 1
            tags = ["old", "new-tag"] if get_calls["n"] > 1 else ["old"]
            return FakeResp(
                200,
                {
                    "data": {
                        "_id": {"$oid": A},
                        "tester_tags": tags,
                        "huge_list": list(range(50)),
                    }
                },
            )

        def fake_put(url, **kwargs):
            put_bodies.append(kwargs.get("json"))
            # Auth must be present — unauthenticated PUT is rejected by JITA
            self.assertIn("auth", kwargs)
            return FakeResp(
                200,
                {"message": "Successfully updated the AgaveTask", "success": True, "data": {}},
            )

        with mock.patch.object(ns["requests"], "get", fake_get), mock.patch.object(
            ns["requests"], "put", fake_put
        ):
            result = fn(A_UP, "new-tag")

        self.assertTrue(result["success"], result)
        self.assertEqual(put_bodies, [{"tester_tags": ["old", "new-tag"]}])
        self.assertEqual(get_calls["n"], 2)  # fetch + verify


if __name__ == "__main__":
    unittest.main()
