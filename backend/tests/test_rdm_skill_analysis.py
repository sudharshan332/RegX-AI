"""Map triage-rdm-deployment-failure skill JSON to JITA comments / Jira actions."""
import os
import re
import unittest

SAMPLE_NODE_MESSAGE = (
    'Installer errors:\n\n'
    'Nodes: kylun01-1: Received "fatal" in waiting for event "Running CVM Installer": boom'
)


def _load_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _extract_node_names(")
    end = src.index("\ndef fetch_jita_deployments(")
    ns = {"re": re}
    exec(src[start:end], ns)  # noqa: S102
    return ns


class TestRdmSkillAnalysisMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def _normalize(self, analysis, rdm_message=""):
        return self.ns["_normalize_rdm_skill_analysis"](analysis, rdm_message)

    def test_link_existing_dial_ticket(self):
        mapped = self._normalize({
            "root_cause": "Same Foundation imaging failure as DIAL-23079",
            "issue_category": "FOUNDATION",
            "existing_tickets": [
                {"ticket": "DIAL-23079", "project": "DIAL", "match": "same root cause"},
            ],
            "recommended_action": "link_existing",
        })
        self.assertEqual(mapped["recommended_action"], "link_existing")
        self.assertEqual(mapped["suggested_comment"], "regx_rerun (DIAL-23079)")
        self.assertEqual(mapped["jira_refs"], ["DIAL-23079"])
        self.assertEqual(mapped["jira_ticket"], "DIAL-23079")
        self.assertFalse(mapped["jira_create"]["needed"])
        self.assertEqual(mapped["suggested_jira_project"], "DIAL")

    def test_infers_link_existing_from_tickets_without_action(self):
        mapped = self._normalize({
            "classification": "Infra Issue",
            "jira_duplicates": ["ENG-12345"],
        })
        self.assertEqual(mapped["recommended_action"], "link_existing")
        self.assertEqual(mapped["suggested_comment"], "regx_rerun (ENG-12345)")
        self.assertEqual(mapped["suggested_jira_project"], "ENG")

    def test_intermittent_rerun_comment(self):
        mapped = self._normalize({
            "issue_category": "INTERMITTENT",
            "root_cause": "Transient pool exhaustion; retry is safe",
        })
        self.assertEqual(mapped["recommended_action"], "rerun")
        self.assertEqual(mapped["suggested_comment"], "regx_rerun")
        self.assertFalse(mapped["jira_create"]["needed"])

    def test_create_jira_for_foundation_without_ticket(self):
        mapped = self._normalize({
            "issue_category": "FOUNDATION",
            "root_cause": "AOS installation failed during Installing AHV",
            "triage_report": "Foundation imaging failed on nested AHV",
        })
        self.assertEqual(mapped["recommended_action"], "create_jira")
        self.assertTrue(mapped["jira_create"]["needed"])
        self.assertEqual(mapped["jira_create"]["project"], "DIAL")
        self.assertEqual(mapped["suggested_comment"], "regx_rerun")
        self.assertIn("Foundation imaging", mapped["jira_create"]["description"])

    def test_disable_node_from_rdm_message(self):
        mapped = self._normalize({}, SAMPLE_NODE_MESSAGE)
        self.assertEqual(mapped["recommended_action"], "disable_node_and_rerun")
        self.assertIn("kylun01-1", mapped["failed_nodes"])
        self.assertIn("regx_rerun_disable-kylun01-1", mapped["suggested_comment"])
        self.assertEqual(mapped["suggested_next_action"], "disable_node_and_rerun")

    def test_product_create_jira_uses_eng(self):
        mapped = self._normalize({
            "issue_category": "PRODUCT",
            "root_cause": "genesis node lock during cluster create",
        })
        self.assertEqual(mapped["recommended_action"], "create_jira")
        self.assertEqual(mapped["suggested_jira_project"], "ENG")


if __name__ == "__main__":
    unittest.main()
