"""Unit tests for NAI client helpers (no live network)."""
import unittest
from unittest.mock import patch

import nai_client


class TestNaiClient(unittest.TestCase):
    def test_resolve_model_aliases(self):
        self.assertEqual(nai_client.resolve_model("nemotron-3-fp4-04"), "nemotron3-fp4-uni")
        self.assertEqual(nai_client.resolve_model("hack-reason"), "nemotron3-fp4-uni")
        self.assertEqual(nai_client.resolve_model(None), "nemotron3-fp4-uni")

    def test_sanitize_api_key_strips_bearer_and_quotes(self):
        self.assertEqual(
            nai_client.sanitize_api_key('Bearer  abc-123 '),
            "abc-123",
        )
        self.assertEqual(nai_client.sanitize_api_key('"abc-123"'), "abc-123")
        self.assertEqual(nai_client.sanitize_api_key("crsr****mnop"), "")

    def test_looks_like_key_name(self):
        self.assertTrue(nai_client.looks_like_key_name("CDP-DPRO-5192-AINTNX-1047"))
        self.assertFalse(nai_client.looks_like_key_name("4f990cff-bbcc-4d15-aa19-9436ce3b8308"))

    def test_cosine_similarity(self):
        self.assertAlmostEqual(nai_client.cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(nai_client.cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_parse_json_object(self):
        self.assertEqual(
            nai_client.parse_json_object('{"root_cause": "x", "classification": "Test Issue"}'),
            {"root_cause": "x", "classification": "Test Issue"},
        )
        self.assertEqual(
            nai_client.parse_json_object('noise ```json\n{"a": 1}\n```'),
            {"a": 1},
        )

    @patch.object(nai_client, "chat_completions")
    def test_chat_text(self, mock_chat):
        mock_chat.return_value = {
            "choices": [{"message": {"content": " hello "}}],
        }
        self.assertEqual(
            nai_client.chat_text("sys", "user", api_key="test-key"),
            "hello",
        )
        args, kwargs = mock_chat.call_args
        self.assertEqual(kwargs["api_key"], "test-key")
        self.assertEqual(args[0][0]["role"], "system")

    @patch.object(nai_client, "_validate_embed_key")
    @patch.object(nai_client, "_validate_chat_key")
    def test_validate_api_key_reports_both(self, mock_chat, mock_embed):
        mock_chat.return_value = {"valid": False, "message": "Unauthorized on Reasoning"}
        mock_embed.return_value = {"valid": True, "message": "Embedding OK"}
        result = nai_client.validate_api_key("chat-key", embed_api_key="embed-key")
        self.assertFalse(result["valid"])
        self.assertIn("Reasoning:", result["message"])
        self.assertIn("Embedding:", result["message"])
        self.assertTrue(result["embedding"]["valid"])
        # Embed validated first, then chat (and retry with embed key).
        self.assertGreaterEqual(mock_embed.call_count, 1)
        self.assertGreaterEqual(mock_chat.call_count, 1)

    def test_headers_both_style_includes_authorization(self):
        headers = nai_client._headers("abc-123", auth_style="both")
        self.assertEqual(headers.get("Authorization"), "Bearer abc-123")
        self.assertEqual(headers.get("api-key"), "abc-123")

    def test_chat_base_candidates_corp_first(self):
        nai_client._WORKING_EMBED["base"] = (
            "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/v1"
        )
        nai_client._WORKING_CHAT["base"] = ""
        bases = nai_client._chat_base_candidates()
        self.assertTrue(bases[0].startswith("https://nai-dre.corp."))
        self.assertIn("/gateway/v1", bases[0])
        # Beta must not be preferred just because embeddings authenticated there.
        self.assertNotIn("nai-dre.beta.", bases[0])

    def test_normalize_failing_code_object_passthrough(self):
        self.assertEqual(
            nai_client._normalize_failing_code(
                {"file": "a.py", "line_range": "10-20", "snippet": "foo()"}
            ),
            {"file": "a.py", "line_range": "10-20", "snippet": "foo()"},
        )
        self.assertEqual(
            nai_client._normalize_failing_code({"path": "b.py", "lines": "1"}),
            {"file": "b.py", "line_range": "1", "snippet": ""},
        )
        # Legacy stringified value — surface as snippet so the UI shows something.
        self.assertEqual(
            nai_client._normalize_failing_code("someCall()"),
            {"file": "", "line_range": "", "snippet": "someCall()"},
        )
        self.assertEqual(
            nai_client._normalize_failing_code(None),
            {"file": "", "line_range": "", "snippet": ""},
        )

    def test_normalize_str_list(self):
        self.assertEqual(nai_client._normalize_str_list(None), [])
        self.assertEqual(
            nai_client._normalize_str_list(["a", "", "b"]),
            ["a", "b"],
        )
        self.assertEqual(nai_client._normalize_str_list("single"), ["single"])

    def test_normalize_tg_validation(self):
        self.assertEqual(
            nai_client._normalize_tg_validation(
                {"ticket": "ENG-1", "verdict": "Correct", "reason": "match"}
            ),
            {"ticket": "ENG-1", "verdict": "Correct", "reason": "match"},
        )
        self.assertEqual(
            nai_client._normalize_tg_validation(None, fallback_ticket="ENG-2"),
            {"ticket": "ENG-2", "verdict": "", "reason": ""},
        )

    @patch.object(nai_client, "chat_text")
    def test_analyze_testcase_with_nai_cdp_builds_triage_report(self, mock_chat):
        model_response = (
            '{\n'
            '  "root_cause": "stargate FATAL at block_store.cc:718",\n'
            '  "classification": "Product Issue",\n'
            '  "confidence": "High",\n'
            '  "suggested_fix": "Investigate CVM .99",\n'
            '  "failing_code": {"file": "block_store.cc", "line_range": "718",'
            '    "snippet": "CHECK(backing_store_)"},\n'
            '  "related_components": ["stargate", "block_store"],\n'
            '  "jira_duplicates": ["ENG-654321"],\n'
            '  "tg_ticket_validation": {"ticket": "ENG-111",'
            '    "verdict": "Incorrect", "reason": "different signature"},\n'
            '  "triage_report": "h2. Bug Report: stargate FATAL\\n\\n'
            'h3. Test Information\\n* *Testcase*: cdp.foo.bar\\n\\n'
            'h3. Failure Summary\\nstargate FATAL at block_store.cc:718.\\n\\n'
            'h3. Related Tickets\\n* ENG-654321 — Similar\\n\\n'
            'h3. Links\\n* [Log Bundle|http://logs/x]"\n'
            "}"
        )
        mock_chat.return_value = model_response
        analysis = nai_client.analyze_testcase_with_nai(
            testcase_name="cdp.foo.bar",
            exception_summary="stargate crashed",
            exception="FATAL ...",
            test_log_url="http://logs/x",
            jira_tickets=["ENG-999"],
            triage_genie_ticket="ENG-111",
            analysis_type="failed",
        )
        self.assertEqual(analysis["provider"], "nai")
        self.assertEqual(analysis["classification"], "Product Issue")
        self.assertEqual(
            analysis["failing_code"],
            {"file": "block_store.cc", "line_range": "718", "snippet": "CHECK(backing_store_)"},
        )
        self.assertEqual(analysis["related_components"], ["stargate", "block_store"])
        self.assertEqual(analysis["jira_duplicates"], ["ENG-654321"])
        self.assertEqual(analysis["tg_ticket_validation"]["verdict"], "Incorrect")
        # Full JIRA-wiki triage report must be preserved for the "Skill Triage
        # Report" section of the Deep AI "View details" modal.
        self.assertIn("h2. Bug Report", analysis["triage_report"])
        self.assertIn("h3. Test Information", analysis["triage_report"])
        self.assertIn("h3. Failure Summary", analysis["triage_report"])
        self.assertIn("h3. Related Tickets", analysis["triage_report"])
        self.assertIn("h3. Links", analysis["triage_report"])
        # The system prompt we routed to the model must contain the mandatory
        # section checklist so non-reasoning NAI models still produce the
        # structured report.
        system_prompt = mock_chat.call_args[0][0]
        self.assertIn("triage_report", system_prompt)
        self.assertIn("Test Information", system_prompt)
        self.assertIn("Failure Summary", system_prompt)
        self.assertIn("Related Tickets", system_prompt)
        self.assertIn("JIRA wiki markup", system_prompt)
        # NAI has no MCP; the prompt must tell the model to work with the
        # provided evidence and flag gaps instead of fabricating them.
        self.assertIn("without live MCP tool access", system_prompt)

    @patch.object(nai_client, "chat_text")
    def test_analyze_testcase_with_nai_falls_back_when_model_emits_prose(self, mock_chat):
        mock_chat.return_value = (
            "stargate crashed because of X.\n\nh3. Failure Summary\nFATAL on CVM .99"
        )
        analysis = nai_client.analyze_testcase_with_nai(
            testcase_name="cdp.foo.bar", exception_summary="stargate crashed"
        )
        # Even when the model forgets JSON, we must never return a blank
        # Skill Triage Report — that's the bug the user hit on NAI SDK.
        self.assertTrue(analysis["triage_report"])
        self.assertIn("Failure Summary", analysis["triage_report"])
        self.assertEqual(
            analysis["failing_code"], {"file": "", "line_range": "", "snippet": ""}
        )
        self.assertEqual(analysis["classification"], "Unknown")

    @patch.object(nai_client, "chat_text")
    def test_analyze_testcase_with_nai_skipped_uses_rdm_prompt(self, mock_chat):
        mock_chat.return_value = (
            '{"root_cause": "Foundation failed", "classification": "Foundation Issue",'
            ' "issue_category": "FOUNDATION", "confidence": "Medium",'
            ' "suggested_fix": "retry", "failing_code": {},'
            ' "related_components": ["foundation"],'
            ' "existing_tickets": [{"ticket": "DIAL-123", "project": "DIAL",'
            '   "match": "same error"}],'
            ' "jira_duplicates": ["DIAL-123"],'
            ' "recommended_action": "link_existing",'
            ' "suggested_comment": "regx_rerun (DIAL-123)",'
            ' "suggested_jira_project": "DIAL",'
            ' "tg_ticket_validation": {"ticket": "DIAL-123",'
            '   "verdict": "Correct", "reason": "match"},'
            ' "triage_report": "h2. Skipped Test Triage\\n\\nh3. Links"}'
        )
        analysis = nai_client.analyze_testcase_with_nai(
            testcase_name="cdp.foo.skip",
            rdm_url="https://rdm.example/deploy/1",
            rdm_message="Foundation failed",
            analysis_type="skipped",
        )
        self.assertEqual(analysis["issue_category"], "FOUNDATION")
        self.assertEqual(analysis["recommended_action"], "link_existing")
        self.assertEqual(analysis["suggested_jira_project"], "DIAL")
        self.assertEqual(len(analysis["existing_tickets"]), 1)
        system_prompt = mock_chat.call_args[0][0]
        self.assertIn("triage-rdm-deployment-failure", system_prompt)
        self.assertIn("Deployment Failure Summary", system_prompt)


if __name__ == "__main__":
    unittest.main()
