"""Map triage-rdm-deployment-failure skill JSON to JITA comments / Jira actions."""
import os
import re
import unittest

SAMPLE_NODE_MESSAGE = (
    'Installer errors:\n\n'
    'Nodes: kylun01-1: Received "fatal" in waiting for event "Running CVM Installer": boom'
)

MULTI_NODE_INSTALLER_MESSAGE = (
    "Installer errors:\n\n"
    "Nodes: pitpf06-4: The target node is not in a valid cluster (imaged by fnd)\n\n"
    "pitpf07-2: The target node is not in a valid cluster (imaged by fnd)\n\n"
    "pitpf10-3: The target node is not in a valid cluster (imaged by fnd)\n\n"
    "pitpf05-2: The target node is not in a valid cluster (imaged by fnd)\n"
)


def _load_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("_INSTALLER_NODE_LINE_RE = re.compile(")
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

    def test_multi_node_installer_errors_include_all_nodes(self):
        mapped = self._normalize({}, MULTI_NODE_INSTALLER_MESSAGE)
        expected = ["pitpf06-4", "pitpf07-2", "pitpf10-3", "pitpf05-2"]
        self.assertEqual(mapped["failed_nodes"], expected)
        self.assertEqual(mapped["recommended_action"], "disable_node_and_rerun")
        for name in expected:
            self.assertIn("regx_rerun_disable-%s" % name, mapped["suggested_comment"])
        self.assertIn("Rerun cause due to node issue", mapped["suggested_comment"])

    def test_product_create_jira_uses_eng(self):
        mapped = self._normalize({
            "issue_category": "PRODUCT",
            "root_cause": "genesis node lock during cluster create",
        })
        self.assertEqual(mapped["recommended_action"], "create_jira")
        self.assertEqual(mapped["suggested_jira_project"], "ENG")

    def test_merge_mcp_health_down_if_probe_or_agent_fails(self):
        merge = self.ns["_merge_rdm_mcp_health"]
        merged = merge(
            {
                "glean": {"ok": False, "status": "unavailable"},
                "sourcegraph": {"ok": True, "status": "ok"},
            },
            {"glean": "ok", "sourcegraph": "unavailable", "notes": "sourcegraph timeout"},
        )
        self.assertFalse(merged["glean"]["ok"])
        self.assertFalse(merged["sourcegraph"]["ok"])
        self.assertEqual(merged["notes"], "sourcegraph timeout")

    def test_merge_mcp_health_ok_when_probe_and_agent_ok(self):
        merge = self.ns["_merge_rdm_mcp_health"]
        merged = merge(
            {
                "glean": {"ok": True, "status": "ok"},
                "sourcegraph": {"ok": True, "status": "ok"},
            },
            {"glean": "ok", "sourcegraph": "ok"},
        )
        self.assertTrue(merged["glean"]["ok"])
        self.assertTrue(merged["sourcegraph"]["ok"])


if __name__ == "__main__":
    unittest.main()
