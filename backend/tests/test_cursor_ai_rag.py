"""Unit tests for Cursor AI local-first RAG routing."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cursor_ai_rag as rag  # noqa: E402
import test_flask as tf  # noqa: E402


def _empty_loaders():
    return {
        "failed_analysis": lambda tag: None,
        "triage_accuracy": lambda tag: None,
        "handover": lambda: [],
        "deprecation": lambda: [],
        "rdm_patterns": lambda: [],
    }


def _fixture_loaders():
    failed = {
        "tag": "752_rc1",
        "saved_at": "2026-09-09T12:24:36Z",
        "results": [
            {
                "testcase_name": "cdp.stargate.rdma.test_io.RDMATest.test_io_integrity",
                "testcase_id": "tid-stargate-1",
                "jira_tickets": ["ENG-977205"],
                "regression_owner": "Thanuja",
                "status": "Failed",
                "exception_summary": "IntegrityTesterShellWorkload timeout on RDMA path",
                "failure_stage": "Test Body",
                "triage_genie_ticket_id": "ENG-972335",
            },
            {
                "testcase_name": "cdp.blockstore.xmount.test_xmount.XmountTest.test_basic",
                "testcase_id": "tid-blockstore-1",
                "jira_tickets": ["ENG-111222"],
                "regression_owner": "Alex",
                "status": "Failed",
                "exception_summary": "xmount assert failed",
            },
            {
                "testcase_name": "robo.robo_two_node.test_robo.RoboTest.test_io",
                "testcase_id": "tid-robo-ticketed",
                "jira_tickets": ["AUTO-27813"],
                "regression_owner": "Swapnil",
                "status": "Failed",
                "exception_summary": "robo node add failed during IO",
                "triage_genie_ticket_id": "ENG-944188",
            },
            {
                "testcase_name": "robo.robo_add_remove_node.test_robo.RoboTest.test_remove_node",
                "testcase_id": "tid-robo-open",
                "jira_tickets": [],
                "regression_owner": "Swapnil",
                "status": "Failed",
                "exception_summary": "robo node add failed during IO",
            },
        ],
    }
    triage = {
        "tag": "752_rc1",
        "testcases": [
            {
                "testcase_name": "cdp.stargate.rdma.test_io.RDMATest.test_io_integrity",
                "regression_owner": "Thanuja",
                "status": "Failed",
                "jira_ticket": "ENG-977205",
                "match_status": "matched",
            },
        ],
    }
    handover = [
        {
            "test_name": "cdp.external_storage.zookeeper.test_zk.ZkTest.test_copy",
            "handover_tickets": ["ENG-124213"],
            "handover_date": "2026-09-08T16:15:26",
            "by_whom": "swapnil",
            "branch": "master",
            "lst_file": "regression_cdp_nutest_official_external_storage_pure.lst",
        },
    ]
    deprecation = [
        {
            "test_name": "robo.robo_add_remove_node.test_robo.RoboTest.test_remove",
            "deprecation_date": "2026-09-21T14:21:59",
            "by_whom": "unknown",
            "jira_tickets": ["ENG-123123"],
            "cr_status": "pending_manual",
        },
    ]
    rdm = [
        {
            "id": "nested_vm_qemu_ram_exhaustion",
            "description": "QEMU ran out of physical memory",
            "root_cause": "Base cluster RAM exhausted",
            "jira": "PI-20705",
            "category": "INFRA_RESOURCE",
        },
    ]
    return {
        "failed_analysis": lambda tag: failed,
        "triage_accuracy": lambda tag: triage,
        "handover": lambda: handover,
        "deprecation": lambda: deprecation,
        "rdm_patterns": lambda: rdm,
    }


class TestCursorAiRagIntent(unittest.TestCase):
    def test_component_count_is_existing_local(self):
        self.assertEqual(
            rag.classify_intent("how many passed from blockstore"),
            rag.INTENT_EXISTING_LOCAL,
        )

    def test_overall_summary_is_existing_local(self):
        self.assertEqual(
            rag.classify_intent("give me summary of this regression run"),
            rag.INTENT_EXISTING_LOCAL,
        )

    def test_counter_substring_is_not_a_count_question(self):
        intent = rag.classify_intent("tell me about blockstore counters")
        self.assertNotEqual(intent, rag.INTENT_EXISTING_LOCAL)
        self.assertFalse(tf._is_component_test_question("tell me about blockstore counters"))

    def test_ticket_lookup_intent(self):
        self.assertEqual(
            rag.classify_intent("what tests have ENG-977205"),
            rag.INTENT_LOOKUP_TICKET,
        )

    def test_handover_intent(self):
        self.assertEqual(
            rag.classify_intent("was cdp.external_storage.zookeeper.test_zk.ZkTest.test_copy handed over?"),
            rag.INTENT_LOOKUP_HANDOVER,
        )

    def test_synthesize_intent(self):
        self.assertEqual(
            rag.classify_intent("explain the root cause of the rdma integrity timeouts"),
            rag.INTENT_SYNTHESIZE,
        )
        self.assertEqual(
            rag.classify_intent(
                "why did cdp.stargate.rdma.test_io.RDMATest.test_io_integrity fail"
            ),
            rag.INTENT_SYNTHESIZE,
        )


class TestCursorAiRagAnswers(unittest.TestCase):
    def setUp(self):
        rag.clear_corpus_cache()
        self.loaders = _fixture_loaders()

    def tearDown(self):
        rag.clear_corpus_cache()

    def _answer(self, question, call_ai=None, loaders=None, context=""):
        return rag.answer_chat_question(
            question,
            tag="752_rc1",
            regression_context=context,
            loaders=loaders if loaders is not None else self.loaders,
            call_ai=call_ai,
            cache_key=False,
        )

    def test_existing_local_falls_through(self):
        self.assertIsNone(self._answer("how many passed from blockstore"))

    def test_empty_corpus_falls_through(self):
        self.assertIsNone(
            self._answer("why did the stargate tests fail", loaders=_empty_loaders())
        )

    def test_ticket_lookup_is_local_and_skips_ai(self):
        calls = []

        def spy_ai(system, user):
            calls.append((system, user))
            return "SHOULD NOT RUN"

        result = self._answer("what tests have ENG-977205", call_ai=spy_ai)
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "local")
        self.assertIn("ENG-977205", result["reply"])
        self.assertIn("Thanuja", result["reply"])
        self.assertIn("cdp.stargate.rdma.test_io.RDMATest.test_io_integrity", result["reply"])
        self.assertEqual(calls, [])

    def test_owner_lookup_local(self):
        result = self._answer("tests owned by Thanuja")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "local")
        self.assertIn("Thanuja", result["reply"])
        self.assertIn("test_io_integrity", result["reply"])
        self.assertNotIn("XmountTest", result["reply"])

    def test_test_name_lookup_local(self):
        result = self._answer(
            "status of cdp.blockstore.xmount.test_xmount.XmountTest.test_basic"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "local")
        self.assertIn("xmount assert failed", result["reply"])
        self.assertIn("Alex", result["reply"])

    def test_handover_lookup_local(self):
        result = self._answer("was cdp.external_storage.zookeeper.test_zk.ZkTest.test_copy handed over?")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "local")
        self.assertIn("ENG-124213", result["reply"])
        self.assertIn("swapnil", result["reply"])

    def test_deprecation_lookup_local(self):
        result = self._answer("is robo.robo_add_remove_node.test_robo.RoboTest.test_remove deprecated?")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "local")
        self.assertIn("ENG-123123", result["reply"])
        self.assertIn("pending_manual", result["reply"])

    def test_list_failed_local(self):
        result = self._answer("list the failed tests")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "local")
        self.assertIn("test_io_integrity", result["reply"])
        self.assertIn("XmountTest", result["reply"])

    def test_create_ticket_for_robo_reuses_existing_key(self):
        self.assertEqual(
            rag.classify_intent("create a ticket for the robo issue"),
            rag.INTENT_CREATE_TICKET,
        )
        result = self._answer("create a ticket for the robo issue")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "local")
        self.assertIn("AUTO-27813", result["reply"])
        self.assertIn("Do **not** create a new Jira ticket", result["reply"])
        self.assertIn("tid-robo-open", result.get("test_ids") or [])
        self.assertIn("attach AUTO-27813", result["reply"])
        self.assertNotIn("Here is the regression run summary", result["reply"])
        self.assertNotIn("XmountTest", result["reply"])
        self.assertLess(result["reply"].count("robo."), 12)

    def test_create_ticket_without_component_asks_for_scope(self):
        result = self._answer("create a ticket")
        self.assertIsNotNone(result)
        self.assertIn("Which component", result["reply"])
        self.assertNotIn("Here is the regression run summary", result["reply"])

    def test_create_ticket_unticketed_only_drafts(self):
        loaders = _fixture_loaders()
        loaders["failed_analysis"] = lambda tag: {
            "tag": "752_rc1",
            "results": [
                {
                    "testcase_name": "robo.robo_two_node.test_robo.RoboTest.test_io",
                    "testcase_id": "tid-robo-open",
                    "jira_tickets": [],
                    "regression_owner": "Swapnil",
                    "status": "Failed",
                    "exception_summary": "robo node add failed during IO",
                }
            ],
        }
        loaders["triage_accuracy"] = lambda tag: {"testcases": []}
        result = self._answer("create a ticket for the robo issue", loaders=loaders)
        self.assertIsNotNone(result)
        self.assertIn("No Jira", result["reply"])
        self.assertIn("CreateIssue", result["reply"])
        self.assertNotIn("Do **not** create a new Jira ticket", result["reply"])

    def test_missing_ticket_falls_through(self):
        self.assertIsNone(self._answer("what tests have ENG-000000"))

    def test_retrieve_keyword_without_ai(self):
        result = self._answer("tell me about stargate rdma IntegrityTester")
        self.assertIsNotNone(result)
        self.assertIn(result["source"], ("local", "rag"))
        self.assertIn("test_io_integrity", result["reply"])
        self.assertNotIn("XmountTest", result["reply"])

    def test_synthesis_calls_ai_with_retrieved_chunks(self):
        def fake_ai(system, user):
            self.assertIn("retrieved records", user.lower())
            self.assertIn("IntegrityTester", user)
            self.assertIn("answer only from", system.lower())
            return "RDMA integrity timeout; owner Thanuja."

        result = self._answer(
            "why did cdp.stargate.rdma.test_io.RDMATest.test_io_integrity fail",
            call_ai=fake_ai,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "ai")
        self.assertIn("RDMA integrity timeout", result["reply"])

    def test_synthesis_falls_back_to_retrieved_facts_when_ai_fails(self):
        def boom(_system, _user):
            raise RuntimeError("AI down")

        result = self._answer("explain the root cause of the stargate rdma failures", call_ai=boom)
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "rag")
        self.assertIn("test_io_integrity", result["reply"])

    def test_unrelated_question_falls_through_to_cursor(self):
        self.assertIsNone(self._answer("write a python fibonacci function"))

    def test_rdm_pattern_retrieval(self):
        result = self._answer("what is the qemu ram exhaustion pattern")
        self.assertIsNotNone(result)
        self.assertIn("nested_vm_qemu_ram_exhaustion", result["reply"])
        self.assertIn("PI-20705", result["reply"])


class TestCursorAiRagFlaskHelper(unittest.TestCase):
    def test_flask_helper_uses_rag_without_calling_cursor(self):
        loaders = _fixture_loaders()
        with patch.object(tf, "load_failed_analysis_results", loaders["failed_analysis"]), \
             patch.object(tf, "load_triage_accuracy_data", loaders["triage_accuracy"]), \
             patch.object(tf, "_load_handover_records", loaders["handover"]), \
             patch.object(tf, "_load_deprecation_records", loaders["deprecation"]), \
             patch.object(tf, "_rag_rdm_pattern_dicts", loaders["rdm_patterns"]), \
             patch.object(tf, "_call_ai_chat") as mock_ai:
            mock_ai.side_effect = AssertionError("AI should not run for ticket lookup")
            result = tf._try_cursor_ai_rag_answer(
                "what tests have ENG-977205",
                tag="752_rc1",
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "local")
        self.assertIn("Thanuja", result["reply"])

    def test_local_or_rag_does_not_dump_qi_for_ticket_create(self):
        loaders = _fixture_loaders()
        ctx = "Regression run: 752_rc1\nTotal tasks: 397\n"
        with patch.object(tf, "load_failed_analysis_results", loaders["failed_analysis"]), \
             patch.object(tf, "load_triage_accuracy_data", loaders["triage_accuracy"]), \
             patch.object(tf, "_load_handover_records", loaders["handover"]), \
             patch.object(tf, "_load_deprecation_records", loaders["deprecation"]), \
             patch.object(tf, "_rag_rdm_pattern_dicts", loaders["rdm_patterns"]), \
             patch.object(tf, "_call_ai_chat") as mock_ai:
            mock_ai.side_effect = AssertionError("AI should not run for robo ticket lookup")
            reply, source = tf._local_or_rag_chat_reply(
                "create a ticket for the robo issue",
                regression_context=ctx,
                tag="752_rc1",
            )
        self.assertIsNotNone(reply)
        self.assertNotEqual(source, "regression_context")
        self.assertNotIn("Here is the regression run summary", reply)
        self.assertIn("AUTO-27813", reply)
        self.assertIn("Do **not** create a new Jira ticket", reply)

    def test_attach_confirm_updates_jita(self):
        loaders = _fixture_loaders()
        tf._clear_chat_attach("tester")
        with patch.object(tf, "load_failed_analysis_results", loaders["failed_analysis"]), \
             patch.object(tf, "load_triage_accuracy_data", loaders["triage_accuracy"]), \
             patch.object(tf, "_load_handover_records", loaders["handover"]), \
             patch.object(tf, "_load_deprecation_records", loaders["deprecation"]), \
             patch.object(tf, "_rag_rdm_pattern_dicts", loaders["rdm_patterns"]), \
             patch.object(tf, "_call_ai_chat") as mock_ai, \
             patch.object(tf, "_get_user_credentials", return_value=("tester", "pw")), \
             patch.object(tf, "_put_jita_triage_tickets", return_value=(True, None)) as mock_put, \
             patch.object(tf, "save_failed_analysis_results"):
            mock_ai.side_effect = AssertionError("AI should not run")
            reply, source = tf._local_or_rag_chat_reply(
                "create a ticket for the robo issue",
                tag="752_rc1",
                username="tester",
            )
            self.assertIn("attach AUTO-27813", reply)
            reply2, source2 = tf._local_or_rag_chat_reply(
                "attach AUTO-27813",
                tag="752_rc1",
                username="tester",
            )
        self.assertEqual(source2, "local")
        self.assertIn("Attached", reply2)
        self.assertTrue(mock_put.called)
        attached_ids = [c.args[0] for c in mock_put.call_args_list]
        self.assertIn("tid-robo-open", attached_ids)
        self.assertNotIn("tid-robo-ticketed", attached_ids)

    def test_local_or_rag_answers_what_is_the_qi(self):
        ctx = "Regression run: 752_rc1\nTotal tasks: 397\n"
        reply, source = tf._local_or_rag_chat_reply(
            "what is the qi",
            regression_context=ctx,
            tag="752_rc1",
        )
        self.assertEqual(source, "regression_context")
        self.assertIn("752_rc1", reply)


if __name__ == "__main__":
    unittest.main()
