"""Unit tests for Cursor AI local component / summary question routing."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import test_flask as tf  # noqa: E402


class TestCursorAiComponentQa(unittest.TestCase):
    def test_extract_component_blockstore(self):
        self.assertEqual(
            tf._extract_component_from_question("how many passed from blockstore"),
            "blockstore",
        )

    def test_component_question_not_overall_summary(self):
        q = "how many passed from blockstore"
        self.assertTrue(tf._is_component_test_question(q))
        self.assertFalse(tf._is_overall_summary_question(q))
        self.assertTrue(tf._is_regression_data_question(q))

    def test_counter_substring_is_not_a_count_question(self):
        q = "tell me about blockstore counters"
        self.assertEqual(tf._extract_component_from_question(q), "blockstore")
        self.assertFalse(tf._is_component_test_question(q))
        self.assertIsNone(tf._desired_status_from_question(q))

    def test_overall_summary_without_component(self):
        q = "give me summary of this regression run"
        self.assertFalse(tf._is_component_test_question(q))
        self.assertTrue(tf._is_overall_summary_question(q))

    def test_what_is_the_qi_is_overall_summary(self):
        self.assertTrue(tf._is_overall_summary_question("what is the qi"))
        self.assertTrue(tf._is_regression_data_question("what is the qi"))

    def test_create_ticket_is_not_a_summary_dump(self):
        for q in (
            "create a ticket",
            "create a ticket for the robo issue",
        ):
            self.assertFalse(tf._is_overall_summary_question(q), q)
            self.assertFalse(tf._is_regression_data_question(q), q)

    def test_test_matches_component_path_segment(self):
        self.assertTrue(
            tf._test_matches_component(
                "cdp.blockstore.xmount.test_xmount_basic.XmountBasicTest.test_xmount_basic",
                "blockstore",
            )
        )
        self.assertFalse(
            tf._test_matches_component(
                "cdp.stargate.power_cycling.test_io.PowerCyclingIOIntegrityTest.test_io",
                "blockstore",
            )
        )

    def test_compact_drops_task_id_dump(self):
        ctx = (
            "Regression run: 752_rc1\n"
            "Scope — task_ids (3): aabbcc, ddeeff, 112233\n"
            "Total tasks: 3\n"
        )
        out = tf._compact_regression_context(ctx)
        self.assertNotIn("aabbcc", out)
        self.assertIn("task_ids (3)", out)

    def test_answer_component_passed_list(self):
        fake_tasks = [
            {"_id": {"$oid": "t1"}, "branch": "ganges-7.5.2-stable", "status": "completed"},
        ]
        fake_results = [
            {
                "test": {"name": "cdp.blockstore.a.TestA.test_ok"},
                "status": "Succeeded",
                "agave_task_id": "t1",
            },
            {
                "test": {"name": "cdp.blockstore.b.TestB.test_fail"},
                "status": "Failed",
                "agave_task_id": "t1",
            },
            {
                "test": {"name": "cdp.stargate.c.TestC.test_ok"},
                "status": "Succeeded",
                "agave_task_id": "t1",
            },
        ]
        with patch.object(tf, "fetch_regression_tasks", return_value=fake_tasks), patch.object(
            tf, "fetch_test_results_batch_with_pagination", return_value=fake_results
        ):
            reply = tf._answer_component_test_question(
                "how many passed from blockstore",
                tag="752_rc1",
            )
        self.assertIn("**1** passed", reply)
        self.assertIn("cdp.blockstore.a.TestA.test_ok", reply)
        self.assertNotIn("cdp.stargate", reply)
        self.assertNotIn("test_fail", reply)

    def test_component_scan_prefers_task_ids_over_tag(self):
        fake_tasks = [
            {"_id": {"$oid": "t1"}, "branch": "ganges-7.5.2-stable", "status": "completed"},
        ]
        fake_results = [
            {
                "test": {"name": "cdp.blockstore.a.TestA.test_ok"},
                "status": "Succeeded",
                "agave_task_id": "t1",
            },
        ]
        with patch.object(tf, "fetch_regression_tasks", return_value=fake_tasks) as fetch_tasks, patch.object(
            tf, "fetch_test_results_batch_with_pagination", return_value=fake_results
        ):
            reply = tf._answer_component_test_question(
                "how many passed from blockstore",
                tag="752_rc1",
                task_ids=["t1"],
            )
        fetch_tasks.assert_called_once_with(tag=None, task_ids=["t1"])
        self.assertIn("**1** passed", reply)


if __name__ == "__main__":
    unittest.main()
