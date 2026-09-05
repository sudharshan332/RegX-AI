"""Tests for Cursor deep-analysis ENG ticket creation helpers."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import test_flask as tf  # noqa: E402


class TestCreateEngTicketIntent(unittest.TestCase):
    def test_matches_common_phrases(self):
        phrases = [
            "create a eng ticket",
            "creaet a eng ticket",
            "Create ENG ticket",
            "file a jira ticket",
            "create ticket for this",
            "raise an eng ticket please",
            "create eng",
            "new eng ticket",
        ]
        for p in phrases:
            self.assertTrue(tf.is_create_eng_ticket_intent(p), p)

    def test_rejects_non_create(self):
        phrases = [
            "what is the root cause?",
            "summarize the triage report",
            "list related tickets",
            "open ticket ENG-123",
            "make sense of the ticket",
            "",
        ]
        for p in phrases:
            self.assertFalse(tf.is_create_eng_ticket_intent(p), p)

    def test_cr_and_investigate_intents(self):
        self.assertTrue(tf.is_create_cr_intent("create CR for the fix as well"))
        self.assertTrue(tf.is_create_cr_intent("file a change request"))
        self.assertTrue(tf.is_investigate_ticket_intent("has ENG-957251 been fixed? what is the CR?"))
        self.assertTrue(tf.is_investigate_ticket_intent("what is the status of this ticket"))
        self.assertFalse(tf.is_investigate_ticket_intent("what is the root cause?"))
        self.assertEqual(tf.extract_eng_ticket_keys("see ENG-957251 and eng-1"), ["ENG-957251", "ENG-1"])

    def test_confirm_and_overrides(self):
        self.assertTrue(tf.is_confirm_eng_ticket_intent("yes"))
        self.assertTrue(tf.is_confirm_eng_ticket_intent("yes; Primary Component: Stargate"))
        self.assertTrue(tf.is_confirm_eng_ticket_intent("Primary Component: Curator"))
        self.assertFalse(tf.is_confirm_eng_ticket_intent("what is the root cause?"))
        ov = tf.parse_eng_ticket_field_overrides(
            "yes; Primary Component: Stargate; Affects Version: master; Test Type: Test Bug"
        )
        self.assertEqual(ov["primary_component"], "Stargate")
        self.assertEqual(ov["affects_version"], "master")
        self.assertEqual(ov["test_type"], "Test Bug")


class TestCreateEngJiraTicket(unittest.TestCase):
    @patch.object(tf, "resolve_jira_token", return_value="")
    def test_missing_token(self, _tok):
        result = tf.create_eng_jira_ticket(
            {
                "testcase_name": "cdp.stargate.foo",
                "root_cause": "boom",
                "primary_component": "Stargate",
                "affects_version": "master",
                "confirm": True,
            },
            require_confirm=False,
        )
        self.assertFalse(result["ok"])
        self.assertIn("Jira token", result["error"])

    def test_infers_fields_for_simple_create(self):
        draft = tf.build_eng_ticket_draft({
            "testcase_name": "cdp.stargate.foo.test_bar",
            "root_cause": "Stargate FATAL",
            "related_components": ["upgrade_workflow", "Stargate"],
            "current_branch": "master",
        })
        self.assertEqual(draft["missing"], [])
        self.assertFalse(draft["needs_confirmation"])
        self.assertEqual(draft["primary_component"], "Stargate")
        self.assertEqual(draft["testcase_name"], "cdp.stargate.foo.test_bar")
        self.assertEqual(draft["affects_version"], "master")
        self.assertEqual(draft["fix_version"], "Triage")
        self.assertEqual(draft["regression"], "Yes-build-to-build")
        self.assertEqual(draft["test_type"], "Test Bug")
        self.assertEqual(draft["issue_type"], "Test")
        self.assertEqual(
            tf._infer_affects_version({"current_branch": "ganges-7.6-stable"}),
            "7.6",
        )
        self.assertEqual(tf._infer_test_type({"test_type": "NuTest"}), "Test Bug")
        self.assertEqual(tf._infer_test_type({"classification": "Product Issue"}), "Product Bug")
        self.assertTrue(tf.is_confirm_eng_ticket_intent("**yes**"))

    def test_asks_only_when_required_missing(self):
        result = tf.create_eng_jira_ticket({
            "testcase_name": "",
            "root_cause": "unknown failure",
        }, require_confirm=False)
        self.assertTrue(result.get("needs_user_input"))
        self.assertIn("testcase_name", result["draft"]["missing"])
        self.assertIn("primary_component", result["draft"]["missing"])

    def _mock_createmeta_empty(self, mock_session):
        meta = MagicMock(status_code=200)
        meta.json.return_value = {"values": []}
        mock_session.get.return_value = meta
        # Clear createmeta cache between tests
        tf._eng_createmeta_cache.clear()

    @patch.object(tf, "_enrich_eng_ticket_context", side_effect=lambda ctx: ctx)
    @patch.object(tf, "resolve_jira_token", return_value="fake-token")
    @patch.object(tf, "session")
    def test_create_success_after_confirm(self, mock_session, _tok, _enrich):
        self._mock_createmeta_empty(mock_session)
        ok = MagicMock(status_code=201)
        ok.json.return_value = {"key": "ENG-12345", "id": "1"}
        mock_session.post.return_value = ok

        # Simple "create eng ticket" — no confirm step when fields are inferred.
        result = tf.create_eng_jira_ticket({
            "testcase_name": "cdp.stargate.foo.test_bar",
            "root_cause": "Stargate FATAL in cache_stats_html.cc",
            "classification": "Test Issue",
            "triage_report": "h2. Bug Report\nDetails here",
            "related_components": ["upgrade_workflow", "Stargate"],
            "current_branch": "master",
            "agave_task_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
            "testcase_id": "bbbbbbbbbbbbbbbbbbbbbbbb",
            "test_log_url": (
                "https://jita.eng.nutanix.com/api/v2/log?log_type=test_log"
                "&url=/logs/aaaaaaaaaaaaaaaaaaaaaaaa/cccccccccccccccccccccccc"
                "&lab=phx1&infra=cdp"
            ),
            "exception": "Traceback (most recent call last):\n  boom",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["key"], "ENG-12345")
        payload = mock_session.post.call_args.kwargs["json"]["fields"]
        self.assertEqual(payload["customfield_15160"]["value"], "Stargate")
        self.assertEqual(payload["customfield_18060"], ["cdp.stargate.foo.test_bar"])
        self.assertEqual(payload["versions"], [{"name": "master"}])
        self.assertEqual(payload["fixVersions"], [{"name": "Triage"}])
        self.assertEqual(payload["customfield_13260"]["value"], "Yes-build-to-build")
        self.assertEqual(payload["customfield_18062"]["value"], "Test Bug")
        self.assertEqual(payload["issuetype"]["name"], "Test")
        self.assertNotIn("components", payload)
        self.assertIn("upgrade_workflow", payload["description"])
        self.assertIn("Failed with:", payload["description"])
        self.assertIn("[Jita|", payload["description"])
        self.assertIn("[Triage Genie JSON|", payload["description"])
        self.assertIn("Traceback:", payload["description"])

    @patch.object(tf, "_enrich_eng_ticket_context", side_effect=lambda ctx: ctx)
    @patch.object(tf, "resolve_jira_token", return_value="fake-token")
    @patch.object(tf, "session")
    def test_retries_test_type_candidates(self, mock_session, _tok, _enrich):
        self._mock_createmeta_empty(mock_session)
        bad = MagicMock(status_code=400)
        bad.json.return_value = {"errors": {"customfield_18062": "invalid"}}
        ok = MagicMock(status_code=201)
        ok.json.return_value = {"key": "ENG-42", "id": "9"}
        # First post uses remapped Test Bug (still fails); retry tries next candidates.
        mock_session.post.side_effect = [bad, ok]

        result = tf.create_eng_jira_ticket({
            "testcase_name": "cdp.stargate.t",
            "primary_component": "Stargate",
            "affects_version": "master",
            "confirm": True,
            "test_type": "NuTest",
        }, require_confirm=False)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(mock_session.post.call_count, 2)
        first_payload = mock_session.post.call_args_list[0].kwargs["json"]["fields"]
        self.assertEqual(first_payload["customfield_18062"]["value"], "Test Bug")

    @patch.object(tf, "_enrich_eng_ticket_context", side_effect=lambda ctx: ctx)
    @patch.object(tf, "resolve_jira_token", return_value="fake-token")
    @patch.object(tf, "session")
    def test_maps_branch_version_and_heals_invalid_fields(self, mock_session, _tok, _enrich):
        self._mock_createmeta_empty(mock_session)
        bad = MagicMock(status_code=400)
        bad.json.return_value = {
            "errors": {
                "customfield_18062": "Option id 'null' is not valid",
                "versions": "Version name 'ganges-7.6-stable' is not valid",
                "customfield_13260": "Option id 'null' is not valid",
            }
        }
        ok = MagicMock(status_code=201)
        ok.json.return_value = {"key": "ENG-77", "id": "3"}
        # First post fails; retries eventually succeed (test-type / regression / version loops)
        mock_session.post.side_effect = [bad, bad, bad, ok]

        result = tf.create_eng_jira_ticket({
            "testcase_name": "cdp.curator.foo.test_x",
            "current_branch": "ganges-7.6-stable",
            "root_cause": "timeout",
        })
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["key"], "ENG-77")

    def test_summary_and_type(self):
        summary = tf._build_eng_ticket_summary({
            "testcase_name": "cdp.a.b.test_thing",
            "root_cause": "Observed crash in foo",
        })
        self.assertIn("test_thing", summary)
        self.assertEqual(tf._issue_type_from_classification("Test Issue"), "Test")
        self.assertEqual(tf._issue_type_from_classification("Product Issue"), "Test")
        self.assertEqual(tf._infer_primary_component({
            "testcase_name": "cdp.curator.foo.bar",
        }), "Curator")

    def test_format_investigation(self):
        md = tf.format_eng_investigation_answer({
            "ok": True,
            "key": "ENG-1",
            "url": "https://jira.nutanix.com/browse/ENG-1",
            "summary": "crash",
            "status": "Resolved",
            "resolution": "Fixed",
            "issue_type": "Bug",
            "is_fixed": True,
            "is_open": False,
            "crs": [{"id": "565080", "url": "https://nugerrit.ntnxdpro.com/c/main/+/565080", "status": "MERGED"}],
        })
        self.assertIn("ENG-1", md)
        self.assertIn("Fixed?", md)
        self.assertIn("565080", md)

    def test_tg_style_description_contains_links_and_traceback(self):
        desc = tf._build_eng_ticket_description({
            "testcase_name": "cdp.cassandra_medusa.foo.Bar.test_x",
            "failed_with": "ChakrDB CAS write hung for 63 seconds",
            "nos_branch": "master",
            "nos_commit": "abc123",
            "nos_gbn": 1783899934,
            "pc_branch": "master",
            "pc_commit": "abc123",
            "pc_gbn": 1783899934,
            "regression": "Yes-build-to-build",
            "last_pass_branch": "master",
            "last_pass_at": "2026-07-06T20:13:56",
            "agave_task_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
            "testcase_id": "bbbbbbbbbbbbbbbbbbbbbbbb",
            "test_log_url": (
                "https://jita.eng.nutanix.com/api/v2/log?log_type=test_log"
                "&url=/logs/aaaaaaaaaaaaaaaaaaaaaaaa/cccccccccccccccccccccccc"
                "&lab=phx1&infra=cdp"
            ),
            "test_steps": "1. Start IO\n2. Degrade node",
            "exception": "Traceback (most recent call last):\n  CHECK failed",
            "triage_report": "h2. Deep analysis details",
        })
        self.assertIn("Test case *cdp.cassandra_medusa.foo.Bar.test_x*", desc)
        self.assertIn("Failed with:", desc)
        self.assertIn("ChakrDB CAS write hung", desc)
        self.assertIn("NOS:*master* abc123 (1783899934)", desc)
        self.assertIn("PC :*master* abc123 (1783899934)", desc)
        self.assertIn("Last pass on branch *master*", desc)
        self.assertIn("[Jita|", desc)
        self.assertIn("[Log|", desc)
        self.assertIn("[Triage Genie|", desc)
        self.assertIn("[Triage Genie JSON|", desc)
        self.assertIn("normalized_logs/triage_genie.json", desc)
        self.assertIn("Test Steps:", desc)
        self.assertIn("{noformat}", desc)
        self.assertIn("Traceback:", desc)
        self.assertIn("CHECK failed", desc)

    def test_parse_jita_log_url_parts(self):
        parts = tf._parse_jita_log_url_parts(
            "https://jita.eng.nutanix.com/api/v2/log?log_type=test_log"
            "&url=/logs/aaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbb&lab=phx1&infra=cdp"
        )
        self.assertEqual(parts["task_id"], "aaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(parts["result_dir"], "bbbbbbbbbbbbbbbbbbbbbbbb")
        self.assertEqual(parts["infra"], "cdp")

    def test_infer_gerrit_branch_from_run(self):
        self.assertEqual(
            tf._infer_gerrit_target_branch({"current_branch": "master"})["handoff_branch"],
            "master",
        )
        self.assertEqual(
            tf._infer_gerrit_target_branch({"nutest_branch": "ganges-7.6-stable"})["gerrit_branch"],
            "ganges-7.6-stable",
        )
        self.assertEqual(
            tf._infer_gerrit_target_branch({"current_branch": "ganges-7.6-stable"})["handoff_branch"],
            "ganges-7.6-stable",
        )
        self.assertEqual(
            tf._infer_gerrit_target_branch({
                "current_branch": "ganges-7.6-stable",
                "service": "PC",
            })["handoff_branch"],
            "ganges-7.6-stable-pc",
        )
        self.assertEqual(
            tf._infer_gerrit_target_branch({"branch": "7.6"})["gerrit_branch"],
            "ganges-7.6-stable",
        )
        hint = tf.format_cr_branch_system_hint({
            "testcase_name": "cdp.foo.bar",
            "nutest_branch": "ganges-7.6-stable",
        })
        self.assertIn("refs/for/ganges-7.6-stable", hint)
        self.assertIn('branch="ganges-7.6-stable"', hint)
        self.assertIn("do not default to master", hint.lower())


if __name__ == "__main__":
    unittest.main()
