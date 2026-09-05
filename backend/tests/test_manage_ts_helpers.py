"""Unit tests for Manage TS helper logic."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    start = src.index("def _framework_args_value_to_dict(")
    end = src.index("@app.route(\"/mcp/regression/dynamic-jp/check-existing\"")
    chunk = src[start:end]

    ns = {
        "json": __import__("json"),
        "re": __import__("re"),
        "logger": __import__("types").SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
    }
    exec(chunk, ns)  # noqa: S102
    return ns


class TestJitaTestSetSearchParams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def test_search_params_skip_sort_and_arg_projections(self):
        fn = self.ns["_jita_test_sets_search_params"]
        params = fn('{"name":{"$regex":"CDP","$options":"i"}}', 80)
        self.assertEqual(params["limit"], 80)
        self.assertNotIn("sort", params)
        self.assertNotIn("only", params)

    def test_search_params_cap_limit(self):
        fn = self.ns["_jita_test_sets_search_params"]
        params = fn("{}", 2000)
        self.assertEqual(params["limit"], 200)


class TestManageTsRegexValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def test_regex_query_success(self):
        fn = self.ns["_manage_ts_validate_search_query"]
        self.assertEqual(fn("CDP_Regression_.*", True), "CDP_Regression_.*")

    def test_regex_query_failure(self):
        fn = self.ns["_manage_ts_validate_search_query"]
        with self.assertRaises(ValueError):
            fn("CDP_Regression_([", True)


class TestManageTsCommonArgs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def test_union_of_disjoint_args(self):
        fn = self.ns["_manage_ts_compute_common_args"]
        rows = [
            {"framework_args": {"a": 1}, "test_args": {"x": "1"}},
            {"framework_args": {"b": 2}, "test_args": {"y": "2"}},
        ]
        out = fn(rows)
        self.assertEqual([r["key"] for r in out["framework_args"]], ["a", "b"])
        self.assertFalse(out["framework_args"][0]["multiple_values"])
        self.assertEqual(out["framework_args"][0]["value"], 1)
        self.assertEqual([r["key"] for r in out["test_args"]], ["x", "y"])

    def test_union_counts_all_disjoint_keys(self):
        fn = self.ns["_manage_ts_compute_common_args"]
        rows = [
            {"framework_args": {}, "test_args": {f"a{i}": i for i in range(8)}},
            {"framework_args": {}, "test_args": {f"b{i}": i for i in range(4)}},
            {"framework_args": {}, "test_args": {"c0": 0}},
        ]
        out = fn(rows)
        self.assertEqual(len(out["test_args"]), 13)
        self.assertTrue(all(not r["multiple_values"] for r in out["test_args"]))

    def test_shared_key_with_multiple_values(self):
        fn = self.ns["_manage_ts_compute_common_args"]
        rows = [
            {"framework_args": {"env": "prod"}, "test_args": {"retries": 1}},
            {"framework_args": {"env": "stage"}, "test_args": {"retries": 1}},
        ]
        out = fn(rows)
        self.assertEqual(len(out["framework_args"]), 1)
        self.assertTrue(out["framework_args"][0]["multiple_values"])
        self.assertEqual(out["framework_args"][0]["value"], None)
        self.assertEqual(len(out["test_args"]), 1)
        self.assertFalse(out["test_args"][0]["multiple_values"])
        self.assertEqual(out["test_args"][0]["value"], 1)

    def test_missing_on_some_ts_is_not_multiple_values(self):
        fn = self.ns["_manage_ts_compute_common_args"]
        rows = [
            {"framework_args": {"env": "prod"}, "test_args": {}},
            {"framework_args": {}, "test_args": {}},
            {"framework_args": {"env": "prod"}, "test_args": {}},
        ]
        out = fn(rows)
        self.assertEqual(len(out["framework_args"]), 1)
        self.assertFalse(out["framework_args"][0]["multiple_values"])
        self.assertEqual(out["framework_args"][0]["value"], "prod")


class TestManageTsApplyPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def test_collision_skip_and_overwrite(self):
        fn = self.ns["_manage_ts_apply_plan_to_args"]
        base_framework = {"timeout": 10}
        base_test = {"seed": "123"}
        plan = fn(
            base_framework,
            base_test,
            {"timeout": 20},
            {},
            [
                {"key": "timeout", "value": 30, "category": "framework", "overwrite_existing": False},
                {"key": "seed", "value": "777", "category": "test", "overwrite_existing": True},
            ],
        )
        self.assertEqual(plan["after_framework"]["timeout"], 20)
        self.assertEqual(plan["after_test"]["seed"], "777")
        self.assertEqual(len(plan["collision_skips"]), 1)
        self.assertEqual(plan["collision_skips"][0]["key"], "timeout")
        # Ensure original inputs were not mutated.
        self.assertEqual(base_framework["timeout"], 10)
        self.assertEqual(base_test["seed"], "123")

    def test_edit_skips_test_sets_missing_the_key(self):
        fn = self.ns["_manage_ts_apply_plan_to_args"]
        missing = fn({}, {"seed": "123"}, {"timeout": 20}, {"retries": 3}, [])
        self.assertEqual(missing["after_framework"], {})
        self.assertEqual(missing["after_test"], {"seed": "123"})
        self.assertEqual(missing["changed_framework"], [])
        self.assertEqual(missing["changed_test"], [])

        present = fn({"timeout": 10}, {"retries": 1}, {"timeout": 20}, {"retries": 3}, [])
        self.assertEqual(present["after_framework"]["timeout"], 20)
        self.assertEqual(present["after_test"]["retries"], 3)
        self.assertEqual(len(present["changed_framework"]), 1)
        self.assertEqual(len(present["changed_test"]), 1)

        added = fn({}, {}, {}, {}, [
            {"key": "new_flag", "value": "1", "category": "test", "overwrite_existing": False},
        ])
        self.assertEqual(added["after_test"]["new_flag"], "1")
        self.assertEqual(len(added["changed_test"]), 1)

    def test_empty_values_are_persisted(self):
        fn = self.ns["_manage_ts_apply_plan_to_args"]
        added = fn({}, {}, {}, {}, [
            {"key": "blank", "value": "", "category": "test", "overwrite_existing": False},
        ])
        self.assertEqual(added["after_test"]["blank"], "")
        self.assertEqual(len(added["changed_test"]), 1)

        missing = fn({}, {}, {}, {}, [
            {"key": "blank2", "value": None, "category": "test", "overwrite_existing": False},
        ])
        self.assertEqual(missing["after_test"]["blank2"], "")

        cleared = fn({"a": "old"}, {"b": "keep"}, {"a": ""}, {"b": None}, [])
        self.assertEqual(cleared["after_framework"]["a"], "")
        self.assertEqual(cleared["after_test"]["b"], "")
        self.assertEqual(len(cleared["changed_framework"]), 1)
        self.assertEqual(len(cleared["changed_test"]), 1)

    def test_many_args_edit_and_add(self):
        fn = self.ns["_manage_ts_apply_plan_to_args"]
        base_test = {f"k{i}": str(i) for i in range(80)}
        edits_test = {f"k{i}": ("" if i % 2 == 0 else f"v{i}") for i in range(80)}
        new_args = [
            {"key": f"n{i}", "value": ("" if i == 0 else f"new{i}"), "category": "test", "overwrite_existing": False}
            for i in range(40)
        ]
        plan = fn({"keep": 1}, base_test, {}, edits_test, new_args)
        self.assertEqual(len(plan["after_test"]), 120)
        self.assertEqual(plan["after_test"]["k0"], "")
        self.assertEqual(plan["after_test"]["k1"], "v1")
        self.assertEqual(plan["after_test"]["n0"], "")
        self.assertEqual(plan["after_test"]["n39"], "new39")
        self.assertEqual(plan["after_framework"], {"keep": 1})

    def test_preview_edits_only_test_sets_that_have_the_key(self):
        build_preview_rows = self.ns["_manage_ts_build_preview_rows"]
        rows = [
            {
                "id": "a",
                "name": "A",
                "framework_args": {"timeout": 10},
                "test_args": {},
                "raw": {"name": "A"},
            },
            {
                "id": "b",
                "name": "B",
                "framework_args": {},
                "test_args": {},
                "raw": {"name": "B"},
            },
        ]
        _preview_rows, totals = build_preview_rows(rows, {"timeout": 20}, {}, [])
        self.assertEqual(totals["test_sets"], 2)
        self.assertEqual(totals["changed_test_sets"], 1)

    def test_build_put_payload_does_not_copy_keys_across_fields(self):
        build = self.ns["_manage_ts_build_put_payload"]
        existing = {
            "name": "TS-1",
            "test_args": '{"seed":"1"}',
            "args_map": {"other": "x"},
            "agave_options": {"timeout": 10},
        }
        payload = build(
            existing,
            {"timeout": 20, "from_other_ts": "nope"},
            {"seed": "1", "other": "x", "from_other_ts": "nope"},
            [],
        )
        self.assertEqual(self.ns["json"].loads(payload["test_args"]), {"seed": "1"})
        self.assertEqual(payload["args_map"], {"other": "x"})
        self.assertEqual(payload["agave_options"], {"timeout": 20})
        self.assertNotIn("testArgs", payload)
        self.assertNotIn("frameworkArgs", payload)
        self.assertNotIn("from_other_ts", payload["args_map"])
        self.assertNotIn("from_other_ts", payload["agave_options"])

    def test_extract_prefers_jita_ui_fields_over_stale_strings(self):
        extract_test = self.ns["_manage_ts_extract_test_args"]
        extract_fw = self.ns["_manage_ts_extract_framework_args"]
        self.assertEqual(
            extract_test({"args_map": {"a1": 1}, "test_args": '{"abc":"stale"}'}),
            {"a1": 1},
        )
        self.assertEqual(
            extract_fw({"agave_options": {"z1": 1}, "framework_args": '{"abc":"stale"}'}),
            {"z1": 1},
        )

    def test_build_put_payload_add_new_writes_canonical_when_empty(self):
        build = self.ns["_manage_ts_build_put_payload"]
        payload = build(
            {"name": "TS-2"},
            {},
            {"new_flag": "1"},
            [{"key": "new_flag", "value": "1", "category": "test", "overwrite_existing": False}],
        )
        self.assertEqual(payload["args_map"], {"new_flag": "1"})
        self.assertEqual(self.ns["json"].loads(payload["test_args"]), {"new_flag": "1"})
        self.assertNotIn("testArgs", payload)


class TestManageTsScale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def test_build_preview_rows_for_one_and_hundred(self):
        build_preview_rows = self.ns["_manage_ts_build_preview_rows"]
        single = [
            {
                "id": "ts-1",
                "name": "TS-1",
                "framework_args": {"keep": 1},
                "test_args": {"k": "v"},
                "raw": {"name": "TS-1"},
            }
        ]
        preview_rows, totals = build_preview_rows(single, {"keep": 2}, {}, [])
        self.assertEqual(len(preview_rows), 1)
        self.assertEqual(totals["changed_test_sets"], 1)

        many = []
        for i in range(100):
            many.append(
                {
                    "id": f"ts-{i}",
                    "name": f"TS-{i}",
                    "framework_args": {"keep": 1},
                    "test_args": {"k": "v"},
                    "raw": {"name": f"TS-{i}"},
                }
            )
        preview_rows, totals = build_preview_rows(
            many,
            {"keep": 2},
            {"k": "v2"},
            [{"key": "new_key", "value": "new_val", "category": "test", "overwrite_existing": False}],
        )
        self.assertEqual(len(preview_rows), 100)
        self.assertEqual(totals["test_sets"], 100)
        self.assertEqual(totals["changed_test_sets"], 100)


if __name__ == "__main__":
    unittest.main()
