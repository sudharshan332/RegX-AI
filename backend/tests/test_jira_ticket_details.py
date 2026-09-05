"""Unit tests for Home-page Jira bug-type extraction helpers."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_helpers():
    """Load Jira ticket helpers from test_flask without starting the Flask app."""
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    start = src.index("_JIRA_ISSUE_KEY_RE = re.compile")
    end = src.index("def _fetch_ticket_issuetype(")
    chunk = src[start:end]

    ns = {"re": __import__("re")}
    exec(chunk, ns)  # noqa: S102
    return ns


class TestJiraTicketDetails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = _load_helpers()

    def test_normalize_issue_key_from_url_and_whitespace(self):
        normalize = self.h["_normalize_jira_issue_key"]
        self.assertEqual(normalize("ENG-12345"), "ENG-12345")
        self.assertEqual(normalize(" eng-12345 "), "ENG-12345")
        self.assertEqual(
            normalize("https://jira.nutanix.com/browse/ENG-12345"),
            "ENG-12345",
        )

    def test_categorize_nutanix_issue_types(self):
        categorize = self.h["_categorize_bug_type_from_issuetype"]
        self.assertEqual(categorize("Test"), "Test Bug")
        self.assertEqual(categorize("Bug"), "Product Bug")
        self.assertEqual(categorize("Product Bug"), "Product Bug")
        self.assertEqual(categorize("Environment"), "Environment")
        self.assertIsNone(categorize("Task"))
        self.assertIsNone(categorize(None))

    def test_extract_handles_null_issuetype(self):
        extract = self.h["_extract_jira_ticket_detail"]
        # Previously fields.get("issuetype", {}).get("name") raised AttributeError
        # when issuetype was explicitly null, failing the whole Home-page batch.
        detail = extract({
            "fields": {
                "issuetype": None,
                "status": {"name": "Open"},
            }
        })
        self.assertEqual(detail["status"], "Open")
        self.assertEqual(detail["issue_type"], "Unknown")
        self.assertIsNone(detail["bug_type"])

    def test_extract_categorizes_test_and_bug(self):
        extract = self.h["_extract_jira_ticket_detail"]
        test_detail = extract({
            "fields": {
                "issuetype": {"name": "Test"},
                "status": {"name": "Closed"},
            }
        })
        self.assertEqual(test_detail["issue_type"], "Test")
        self.assertEqual(test_detail["bug_type"], "Test Bug")
        self.assertEqual(test_detail["status"], "Closed")

        bug_detail = extract({
            "fields": {
                "issuetype": {"name": "Bug"},
                "status": {"name": "In Progress"},
            }
        })
        self.assertEqual(bug_detail["bug_type"], "Product Bug")

    def test_extract_missing_payload(self):
        extract = self.h["_extract_jira_ticket_detail"]
        self.assertEqual(
            extract(None),
            {"status": "N/A", "issue_type": "N/A", "bug_type": None},
        )


if __name__ == "__main__":
    unittest.main()
