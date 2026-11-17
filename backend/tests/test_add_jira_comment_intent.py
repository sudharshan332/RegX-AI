"""Deep AI follow-up chat: add-Jira-comment intent + helper."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load the add-comment intent helpers without pulling in the full Flask app.
_SRC = open(
    os.path.join(os.path.dirname(__file__), "..", "test_flask.py"), encoding="utf-8"
).read()
_NS = {"re": re}
for _name in (
    "_ADD_COMMENT_INTENT_RE",
    "_JIRA_KEY_RE",
    "is_add_jira_comment_intent",
    "extract_jira_key_from_text",
    "_format_triage_report_comment",
):
    if _name.startswith("_") and _name.endswith("_RE"):
        _m = re.search(rf"^{_name} = re\.compile\([\s\S]*?\n\)\n", _SRC, re.M)
    else:
        _m = re.search(rf"^def {_name}\(.*?(?=^def |\Z)", _SRC, re.M | re.S)
    assert _m, f"missing: {_name}"
    exec(compile(_m.group(0), _name, "exec"), _NS)


class TestAddJiraCommentIntent(unittest.TestCase):
    def test_user_bug_report_intent(self):
        self.assertTrue(
            _NS["is_add_jira_comment_intent"](
                "Add above Skill Triage Report as a comment in Jira Eng ticket ENG-999279"
            )
        )

    def test_variants(self):
        self.assertTrue(_NS["is_add_jira_comment_intent"]("post this as a comment on ENG-1"))
        self.assertTrue(_NS["is_add_jira_comment_intent"]("append the triage report as a note to ABC-42"))
        self.assertTrue(_NS["is_add_jira_comment_intent"]("Add Comment on ENG-77"))

    def test_rejects_without_jira_key(self):
        self.assertFalse(_NS["is_add_jira_comment_intent"]("add a comment"))
        self.assertFalse(_NS["is_add_jira_comment_intent"]("summarize the triage"))

    def test_rejects_without_add_verb(self):
        self.assertFalse(_NS["is_add_jira_comment_intent"]("show comments on ENG-1"))
        self.assertFalse(_NS["is_add_jira_comment_intent"]("open ENG-1"))

    def test_create_ticket_is_not_a_comment_add(self):
        self.assertFalse(_NS["is_add_jira_comment_intent"]("create ENG ticket for this failure"))

    def test_extract_key(self):
        self.assertEqual(
            _NS["extract_jira_key_from_text"]("comment on eng-999"), "ENG-999"
        )
        self.assertEqual(
            _NS["extract_jira_key_from_text"]("Add note to ABC-77 please"), "ABC-77"
        )
        self.assertIsNone(_NS["extract_jira_key_from_text"]("no key here"))

    def test_format_comment_prefers_triage_report(self):
        body = _NS["_format_triage_report_comment"](
            {"triage_report": "Full report body", "root_cause": "RC"}
        )
        self.assertEqual(body, "Full report body")

    def test_format_comment_builds_from_fields(self):
        body = _NS["_format_triage_report_comment"](
            {
                "testcase_name": "tc.a",
                "classification": "Test Issue",
                "root_cause": "flaky setup",
                "suggested_fix": "retry step",
            }
        )
        self.assertIn("h3. Testcase", body)
        self.assertIn("tc.a", body)
        self.assertIn("h3. Classification", body)
        self.assertIn("Test Issue", body)
        self.assertIn("h3. Root Cause", body)
        self.assertIn("flaky setup", body)
        self.assertIn("h3. Suggested Fix", body)
        self.assertIn("retry step", body)

    def test_format_comment_fallback_when_empty(self):
        body = _NS["_format_triage_report_comment"]({})
        self.assertIn("no triage report text available", body)


if __name__ == "__main__":
    unittest.main()
