"""Each skipped test must map to its own JITA deployment / RDM link."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TIER_WISE_DEPLOYMENT = "6a886b338e79cecfb28712e3"
TIER_WISE_RDM = "6a886b7d7298f618dcba1e46"
FIRST_FAILED_DEPLOYMENT = "6a886b618e79ced60d48b90f"
FIRST_FAILED_RDM = "6a886b6c7298f618eda249cb"


def _load_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _rdm_oid(")
    end = src.index("\ndef get_rdm_failure_info(")
    ns = {
        "session": mock.Mock(),
        "logger": mock.Mock(),
    }
    ns["session"].get.return_value = mock.Mock(status_code=404, json=lambda: {})
    exec(src[start:end], ns)  # noqa: S102
    return ns


def _sample_deployments():
    return [
        {
            "_id": {"$oid": FIRST_FAILED_DEPLOYMENT},
            "status": "failed",
            "provision_request_id": {"$oid": FIRST_FAILED_RDM},
            "status_transitions": [{"status": "failed", "reason": "first task RDM"}],
        },
        {
            "_id": {"$oid": TIER_WISE_DEPLOYMENT},
            "status": "failed",
            "provision_request_id": {"$oid": TIER_WISE_RDM},
            "status_transitions": [{"status": "failed", "reason": "tier_wise RDM"}],
        },
    ]


class TestRdmDeploymentMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def test_without_deployment_id_uses_first_failed(self):
        info = self.ns["_rdm_info_from_deployments"](_sample_deployments())
        self.assertEqual(info["provision_request_id"], FIRST_FAILED_RDM)
        self.assertIn(FIRST_FAILED_RDM, info["rdm_link"])

    def test_deployment_id_selects_that_tests_rdm(self):
        info = self.ns["_rdm_info_from_deployments"](
            _sample_deployments(), deployment_id=TIER_WISE_DEPLOYMENT
        )
        self.assertEqual(info["provision_request_id"], TIER_WISE_RDM)
        self.assertEqual(
            info["rdm_link"],
            f"https://rdm.eng.nutanix.com/scheduled_deployments/{TIER_WISE_RDM}",
        )
        self.assertEqual(info["jita_deployment_id"], TIER_WISE_DEPLOYMENT)
        self.assertEqual(info["rdm_message"], "tier_wise RDM")

    def test_unknown_deployment_id_does_not_fall_back(self):
        info = self.ns["_rdm_info_from_deployments"](
            _sample_deployments(), deployment_id="missing-id"
        )
        self.assertIsNone(info)

    def test_oid_normalizes_dict_and_string(self):
        oid = self.ns["_rdm_oid"]
        self.assertEqual(oid({"$oid": TIER_WISE_RDM}), TIER_WISE_RDM)
        self.assertEqual(oid(TIER_WISE_RDM), TIER_WISE_RDM)
        self.assertEqual(oid(""), "")
        self.assertEqual(oid(None), "")


if __name__ == "__main__":
    unittest.main()
