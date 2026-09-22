"""Unit tests for handover helpers: task-id parsing and sliding eligibility."""

import unittest

from handover_helpers import (
    parse_task_id_inputs,
    parse_jita_url,
    evaluate_sliding_eligibility,
    is_product_bug_only_failure,
    order_runs_for_test,
    categorize_bug_type_from_issuetype,
)


class ParseTaskIdInputsTests(unittest.TestCase):
    def test_hex_ids_comma_space_newline(self):
        a = "aaaaaaaaaaaaaaaaaaaa"
        b = "bbbbbbbbbbbbbbbbbbbb"
        c = "cccccccccccccccccccc"
        self.assertEqual(parse_task_id_inputs("%s, %s\n%s" % (a, b, c)), [a, b, c])

    def test_url_with_task_ids_query(self):
        a = "aaaaaaaaaaaaaaaaaaaa"
        b = "bbbbbbbbbbbbbbbbbbbb"
        url = "https://jita.example/results?task_ids=%s,%s" % (a, b)
        self.assertEqual(parse_task_id_inputs(url), [a, b])

    def test_mixed_url_and_hex(self):
        a = "aaaaaaaaaaaaaaaaaaaa"
        b = "bbbbbbbbbbbbbbbbbbbb"
        c = "cccccccccccccccccccc"
        blob = "https://jita.example/results?task_ids=%s\n%s %s" % (a, b, c)
        self.assertEqual(parse_task_id_inputs(blob), [a, b, c])

    def test_agave_task_path(self):
        tid = "aaaaaaaaaaaaaaaaaaaa"
        self.assertEqual(parse_jita_url("https://jita.example/agave_tasks/%s" % tid), [tid])

    def test_dedupe_preserves_order(self):
        a = "aaaaaaaaaaaaaaaaaaaa"
        b = "bbbbbbbbbbbbbbbbbbbb"
        self.assertEqual(parse_task_id_inputs("%s %s %s" % (a, b, a)), [a, b])

    def test_list_input(self):
        a = "aaaaaaaaaaaaaaaaaaaa"
        b = "bbbbbbbbbbbbbbbbbbbb"
        self.assertEqual(parse_task_id_inputs([a, b]), [a, b])

    def test_empty(self):
        self.assertEqual(parse_task_id_inputs(""), [])
        self.assertEqual(parse_task_id_inputs(None), [])


class EligibilityTests(unittest.TestCase):
    def test_consecutive_pass(self):
        ok, reason, passed = evaluate_sliding_eligibility([
            {"status": "Succeeded", "bug_types": []},
            {"status": "Succeeded", "bug_types": []},
        ])
        self.assertTrue(ok)
        self.assertEqual(reason, "consecutive_pass")
        self.assertEqual(passed, 2)

    def test_product_bug_gap(self):
        ok, reason, passed = evaluate_sliding_eligibility([
            {"status": "Succeeded", "bug_types": []},
            {"status": "Failed", "bug_types": ["Product Bug"]},
            {"status": "Succeeded", "bug_types": []},
        ])
        self.assertTrue(ok)
        self.assertEqual(reason, "product_bug_gap")
        self.assertEqual(passed, 2)

    def test_test_bug_gap_not_eligible(self):
        ok, reason, passed = evaluate_sliding_eligibility([
            {"status": "Succeeded", "bug_types": []},
            {"status": "Failed", "bug_types": ["Test Bug"]},
            {"status": "Succeeded", "bug_types": []},
        ])
        self.assertFalse(ok)
        self.assertIsNone(reason)
        self.assertEqual(passed, 2)

    def test_unknown_failure_breaks_window(self):
        ok, reason, _ = evaluate_sliding_eligibility([
            {"status": "Succeeded", "bug_types": []},
            {"status": "Failed", "bug_types": []},
            {"status": "Succeeded", "bug_types": []},
        ])
        self.assertFalse(ok)
        self.assertIsNone(reason)

    def test_skips_pending_between(self):
        ok, reason, passed = evaluate_sliding_eligibility([
            {"status": "Succeeded", "bug_types": []},
            {"status": "Pending", "bug_types": []},
            {"status": "Succeeded", "bug_types": []},
        ])
        self.assertTrue(ok)
        self.assertEqual(reason, "consecutive_pass")
        self.assertEqual(passed, 2)

    def test_order_runs_skips_missing_tasks(self):
        runs = [
            {"agave_task_id": {"$oid": "t2"}, "status": "Succeeded"},
            {"agave_task_id": {"$oid": "t1"}, "status": "Failed"},
        ]
        ordered = order_runs_for_test(runs, ["t3", "t1", "t2"])
        self.assertEqual([r["agave_task_id"]["$oid"] for r in ordered], ["t1", "t2"])

    def test_product_bug_only_helper(self):
        self.assertTrue(is_product_bug_only_failure(["Product Bug"]))
        self.assertFalse(is_product_bug_only_failure(["Product Bug", "Test Bug"]))
        self.assertFalse(is_product_bug_only_failure([]))

    def test_prefer_non_intransit(self):
        from handover_helpers import prefer_non_intransit_lst, is_intransit_lst_path
        self.assertTrue(is_intransit_lst_path("test_sets/intransit/foo.lst"))
        self.assertFalse(is_intransit_lst_path("test_sets/milestones/7.6/foo.lst"))
        self.assertEqual(
            prefer_non_intransit_lst([
                "test_sets/intransit/a.lst",
                "test_sets/milestones/7.6/b.lst",
            ]),
            "test_sets/milestones/7.6/b.lst",
        )
        self.assertEqual(prefer_non_intransit_lst(["test_sets/intransit/a.lst"]), "")

    def test_categorize_issuetype(self):
        self.assertEqual(categorize_bug_type_from_issuetype("Product Bug"), "Product Bug")
        self.assertEqual(categorize_bug_type_from_issuetype("Test Bug"), "Test Bug")
        self.assertEqual(categorize_bug_type_from_issuetype("Environment"), "Environment")


if __name__ == "__main__":
    unittest.main()
