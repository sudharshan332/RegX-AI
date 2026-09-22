"""Unit tests for handover helpers: task-id parsing and sliding eligibility."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handover_helpers import (  # noqa: E402
    parse_task_id_inputs,
    parse_jita_url,
    parse_handover_input,
    normalize_test_name_list,
    evaluate_sliding_eligibility,
    is_product_bug_only_failure,
    order_runs_for_test,
    categorize_bug_type_from_issuetype,
    select_newest_runs,
    pick_runs_for_test_query,
    filter_runs_for_branch,
    empty_handover_test_case,
    AmbiguousTestNameError,
    parse_record_search_queries,
    filter_records_by_query,
    record_matches_delete_key,
    delete_record_from_list,
    can_delete_record,
    is_record_admin,
    identity_keys,
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


class ParseHandoverInputTests(unittest.TestCase):
    def test_full_dotted_name(self):
        name = "cdp.foo.bar.MyTest.test_basic"
        parsed = parse_handover_input(name)
        self.assertEqual(parsed["task_ids"], [])
        self.assertEqual(parsed["test_names"], [name])

    def test_comma_and_newline_names(self):
        parsed = parse_handover_input("test_a, test_b\ncdp.foo.bar.MyTest.test_basic")
        self.assertEqual(parsed["task_ids"], [])
        self.assertEqual(parsed["test_names"], ["test_a", "test_b", "cdp.foo.bar.MyTest.test_basic"])

    def test_does_not_split_on_dots(self):
        name = "cdp.counter.fio.test_fio_counters.CountersFIOTest.test_fio_end_to_end"
        parsed = parse_handover_input(name)
        self.assertEqual(parsed["test_names"], [name])

    def test_mixed_url_and_names(self):
        a = "aaaaaaaaaaaaaaaaaaaa"
        url = "https://jita.example/results?task_ids=%s" % a
        parsed = parse_handover_input("%s\ncdp.foo.bar.MyTest.test_basic, test_a" % url)
        self.assertEqual(parsed["task_ids"], [a])
        self.assertEqual(parsed["test_names"], ["cdp.foo.bar.MyTest.test_basic", "test_a"])

    def test_mixed_hex_and_name_comma(self):
        a = "aaaaaaaaaaaaaaaaaaaa"
        parsed = parse_handover_input("%s, test_foo" % a)
        self.assertEqual(parsed["task_ids"], [a])
        self.assertEqual(parsed["test_names"], ["test_foo"])

    def test_ignores_jira_keys(self):
        parsed = parse_handover_input("ENG-123, test_foo")
        self.assertEqual(parsed["test_names"], ["test_foo"])
        self.assertEqual(parsed["task_ids"], [])

    def test_dedupe_preserves_order(self):
        parsed = parse_handover_input("test_a, test_b, test_a")
        self.assertEqual(parsed["test_names"], ["test_a", "test_b"])

    def test_list_input(self):
        parsed = parse_handover_input(["test_a", "test_b"])
        self.assertEqual(parsed["test_names"], ["test_a", "test_b"])

    def test_empty(self):
        self.assertEqual(parse_handover_input(""), {"task_ids": [], "test_names": []})
        self.assertEqual(parse_handover_input(None), {"task_ids": [], "test_names": []})

    def test_normalize_test_name_list(self):
        self.assertEqual(normalize_test_name_list("test_a, test_b"), ["test_a", "test_b"])
        self.assertEqual(normalize_test_name_list(["test_a", "test_b"]), ["test_a", "test_b"])
        self.assertEqual(normalize_test_name_list(None), [])


class TestNameMatchAndWindowTests(unittest.TestCase):
    def _run(self, name, branch, start_time, status="Succeeded", tid=None):
        row = {
            "test": {"name": name},
            "system_under_test": {"branch": branch},
            "start_time": start_time,
            "status": status,
            "jira_tickets": [],
            "bug_types": [],
        }
        if tid:
            row["agave_task_id"] = {"$oid": tid}
        return row

    def test_pick_exact_then_suffix(self):
        runs = [
            self._run("cdp.foo.MyTest.test_basic", "master", "2026-09-10"),
            self._run("cdp.foo.MyTest.test_basic_extra", "master", "2026-09-09"),
        ]
        name, matched, ambiguous = pick_runs_for_test_query("cdp.foo.MyTest.test_basic", runs)
        self.assertEqual(name, "cdp.foo.MyTest.test_basic")
        self.assertEqual(len(matched), 1)
        self.assertEqual(ambiguous, [])

        name, matched, ambiguous = pick_runs_for_test_query("test_basic", runs)
        self.assertEqual(name, "cdp.foo.MyTest.test_basic")
        self.assertEqual(len(matched), 1)
        self.assertEqual(ambiguous, [])

    def test_pick_ambiguous_suffix(self):
        runs = [
            self._run("pkg.A.test_foo", "master", "2026-09-10"),
            self._run("pkg.B.test_foo", "master", "2026-09-09"),
        ]
        name, matched, ambiguous = pick_runs_for_test_query("test_foo", runs)
        self.assertIsNone(name)
        self.assertEqual(matched, [])
        self.assertEqual(ambiguous, ["pkg.A.test_foo", "pkg.B.test_foo"])

    def test_filter_runs_for_branch_case_insensitive(self):
        runs = [
            self._run("t.a", "master", "2026-09-10"),
            self._run("t.a", "ganges-7.6-stable", "2026-09-09"),
        ]
        filtered = filter_runs_for_branch(runs, "Master")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["system_under_test"]["branch"], "master")

    def test_filter_runs_for_branch_keeps_missing_branch_field(self):
        runs = [
            {"test": {"name": "t.a"}, "start_time": "2026-09-10"},
            self._run("t.a", "ganges-7.6-stable", "2026-09-09"),
        ]
        filtered = filter_runs_for_branch(runs, "master")
        self.assertEqual(len(filtered), 1)
        self.assertNotIn("system_under_test", filtered[0])

    def test_last_5_window_ignores_older_sixth_run(self):
        # Newest 5: one Succeeded + four Product-Bug failures (not eligible).
        # 6th (oldest) Succeeded would make product_bug_gap if included.
        runs = [
            self._run("t.a", "master", "2026-09-10", "Succeeded", "t1"),
            self._run("t.a", "master", "2026-09-09", "Failed", "t2"),
            self._run("t.a", "master", "2026-09-08", "Failed", "t3"),
            self._run("t.a", "master", "2026-09-07", "Failed", "t4"),
            self._run("t.a", "master", "2026-09-06", "Failed", "t5"),
            self._run("t.a", "master", "2026-09-05", "Succeeded", "t6"),
        ]
        for row in runs[1:5]:
            row["bug_types"] = ["Product Bug"]
        selected = select_newest_runs(runs, 5)
        self.assertEqual(len(selected), 5)
        self.assertEqual([r["agave_task_id"]["$oid"] for r in selected], ["t1", "t2", "t3", "t4", "t5"])
        ok, reason, passed = evaluate_sliding_eligibility(selected)
        self.assertFalse(ok)
        self.assertIsNone(reason)
        self.assertEqual(passed, 1)
        all_ok, all_reason, all_passed = evaluate_sliding_eligibility(select_newest_runs(runs, 6))
        self.assertTrue(all_ok)
        self.assertEqual(all_reason, "product_bug_gap")
        self.assertEqual(all_passed, 2)

    def test_empty_handover_test_case(self):
        tc = empty_handover_test_case("missing.test")
        self.assertEqual(tc["test_name"], "missing.test")
        self.assertEqual(tc["status"], "Failed")
        self.assertEqual(tc["total_count"], 0)

    def test_ambiguous_error_message(self):
        err = AmbiguousTestNameError("foo", ["a.foo", "b.foo"])
        self.assertIn("a.foo", str(err))
        self.assertEqual(err.candidates, ["a.foo", "b.foo"])


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


class RecordListHelperTests(unittest.TestCase):
    def _rows(self):
        return [
            {"test_name": "cdp.foo.test_a", "handover_date": "2026-09-10", "lst_file": "a.lst"},
            {"test_name": "cdp.bar.test_b", "handover_date": "2026-09-12", "lst_file": "b.lst"},
            {"test_name": "cdp.foo.test_a", "handover_date": "2026-09-10", "lst_file": "a.lst"},
        ]

    def test_parse_queries_unique(self):
        self.assertEqual(parse_record_search_queries("test_a, test_b\ntest_a"), ["test_a", "test_b"])
        self.assertEqual(parse_record_search_queries(["foo", "bar", "foo"]), ["foo", "bar"])
        self.assertEqual(parse_record_search_queries(""), [])
        self.assertEqual(parse_record_search_queries(None), [])

    def test_empty_query_returns_all_newest_first(self):
        matches = filter_records_by_query(self._rows(), [], date_field="handover_date")
        self.assertEqual([r["test_name"] for r in matches], ["cdp.bar.test_b", "cdp.foo.test_a"])

    def test_substring_match(self):
        matches = filter_records_by_query(self._rows(), ["foo.test_a"], date_field="handover_date")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["test_name"], "cdp.foo.test_a")

    def test_delete_key_first_match_only(self):
        remaining, removed = delete_record_from_list(
            self._rows(), "cdp.foo.test_a", "2026-09-10", "a.lst", "handover_date"
        )
        self.assertTrue(removed)
        self.assertEqual(len(remaining), 2)
        self.assertFalse(
            record_matches_delete_key(remaining[0], "cdp.foo.test_a", "2026-09-10", "a.lst", "handover_date")
        )
        remaining2, removed2 = delete_record_from_list(
            remaining, "missing", "2026-09-10", "a.lst", "handover_date"
        )
        self.assertFalse(removed2)
        self.assertEqual(len(remaining2), 2)

    def test_deprecation_date_field(self):
        rows = [
            {"test_name": "t.a", "deprecation_date": "2026-09-01", "lst_file": "x.lst"},
            {"test_name": "t.b", "deprecation_date": "2026-09-20", "lst_file": "y.lst"},
        ]
        matches = filter_records_by_query(rows, None, date_field="deprecation_date")
        self.assertEqual([r["test_name"] for r in matches], ["t.b", "t.a"])
        remaining, removed = delete_record_from_list(
            rows, "t.a", "2026-09-01", "x.lst", "deprecation_date"
        )
        self.assertTrue(removed)
        self.assertEqual([r["test_name"] for r in remaining], ["t.b"])


class RecordDeleteAclTests(unittest.TestCase):
    def test_identity_keys_email_and_username(self):
        keys = identity_keys("Alice@Nutanix.com", "bob")
        self.assertIn("alice@nutanix.com", keys)
        self.assertIn("alice", keys)
        self.assertIn("bob", keys)
        self.assertIn("bob@nutanix.com", keys)

    def test_unknown_is_not_creator(self):
        rec = {"by_whom": "unknown"}
        self.assertFalse(can_delete_record(rec, "alice", "alice@nutanix.com"))
        self.assertFalse(can_delete_record({"by_whom": ""}, "alice", "alice@nutanix.com"))
        self.assertFalse(can_delete_record({}, "alice", "alice@nutanix.com"))

    def test_owner_match_email_or_username(self):
        rec = {"by_whom": "alice@nutanix.com"}
        self.assertTrue(can_delete_record(rec, "alice", ""))
        self.assertTrue(can_delete_record(rec, "", "alice@nutanix.com"))
        self.assertTrue(can_delete_record({"by_whom": "alice"}, "alice", "alice@nutanix.com"))
        self.assertFalse(can_delete_record(rec, "bob", "bob@nutanix.com"))

    def test_named_admins_can_delete_any(self):
        rec = {"by_whom": "alice@nutanix.com"}
        unknown = {"by_whom": "unknown"}
        self.assertTrue(can_delete_record(rec, "swapnil.wankhede", "swapnil.wankhede@nutanix.com"))
        self.assertTrue(can_delete_record(unknown, "sudharshan.musali", ""))
        self.assertTrue(is_record_admin("swapnil.wankhede", ""))
        self.assertFalse(is_record_admin("alice", "alice@nutanix.com"))

    def test_jp_delete_admin_env_union(self):
        rec = {"by_whom": "unknown"}
        self.assertFalse(can_delete_record(rec, "jp.admin", "jp.admin@nutanix.com"))
        self.assertTrue(can_delete_record(rec, "jp.admin", "", extra_admins=["jp.admin"]))
        self.assertTrue(is_record_admin("jp.admin", "jp.admin@nutanix.com", extra_admins=["JP.ADMIN"]))


if __name__ == "__main__":
    unittest.main()
