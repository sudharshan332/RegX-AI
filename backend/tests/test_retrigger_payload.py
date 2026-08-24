"""Unit tests for Jita rerun payload construction."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_builder():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _build_rerun_payload(")
    end = src.index("\n# ======================================================\n# Testcase Management")
    ns = {}
    exec(src[start:end], ns)  # noqa: S102
    return ns["_build_rerun_payload"]


class RetriggerPayloadTests(unittest.TestCase):
    def setUp(self):
        self.build = _load_builder()
        self.task = {
            "branch": "ganges-7.6.0.6-stable",
            "commit_id": "fd96efb85c11ac75f282d51dce06e04a279bad2d",
            "gbn": 1786602592,
            "image_gbn": 1786602592,
            "image_commit": "fd96efb85c11ac75f282d51dce06e04a279bad2d",
            "image_branch": "ganges-7.6.0.6-stable",
            "test_framework": "nutest-py3-tests",
            "nutest-py3-tests_commit": "a441cba1b87befb27700b0f48ec24ed1b0e4c8e0",
            "nutest-py3-tests_branch": "ganges-7.6-stable",
            "skip_resource_spec_match": False,
            "check_image_compatibility": True,
            "label": "SM_2008_P4-(3)",
            "tester_tags": ["jita3", "v3.1", "infra__cdp"],
            "resource_manager_json": {
                "NOS_CLUSTER": {
                    "build": {
                        "commit_id": "fd96efb85c11ac75f282d51dce06e04a279bad2d",
                        "gbn": 1786602592,
                        "component": "main",
                        "branch": "ganges-7.6.0.6-stable",
                    }
                },
                "PRISM_CENTRAL": {
                    "build": {
                        "commit_id": "d1dbe83ce298b79b529a756e79af021a31bf1c3d",
                        "gbn": 1787129883,
                        "component": "main",
                        "branch": "ganges-7.6.0.6-stable-pc",
                    }
                },
            },
            "sdk_installation_options": {},
            "test_framework_metadata": {
                "test": {"branch": "ganges-7.6-stable", "commit": "cd63600b640442e1c36666299239920aef4da08a"},
                "framework": {"branch": "ganges-7.6-stable", "commit": "a441cba1b87befb27700b0f48ec24ed1b0e4c8e0"},
            },
            "priority": 10,
            "requested_hardware": {
                "infra": [{
                    "kind": "ON_PREM",
                    "type": "node_pool",
                    "entries": ["Regression_cdp_special_config", "CDP_regression_ESXi_Qual"],
                }]
            },
            "retain_resources_config": {
                "criteria": {
                    "TEST_FAILURE": {
                        "entity": "CONTAINER",
                        "type": "AFTER_EACH",
                        "params": {"duration": 720, "exceptions": [], "states_to_track": ["Failed"]},
                    }
                }
            },
        }
        self.tests = [{
            "test_result_id": "6a86c0aeb5e475da734ee79b",
            "name": "awsclusters.snap2s3.rbac.test_snap2s3_rbac.TestSnap2S3RBAC~~~Cluster_Viewer.test_snap2s3_rbac",
        }]

    def test_copies_full_jita_contract_for_selected_tests(self):
        payload = self.build(self.task, self.tests, {}, "sudharshan.musali")
        self.assertEqual(payload["tests"], self.tests)
        self.assertEqual(payload["branch"], "ganges-7.6.0.6-stable")
        self.assertEqual(payload["commit_id"], self.task["commit_id"])
        self.assertEqual(payload["gbn"], 1786602592)
        self.assertEqual(payload["image_gbn"], 1786602592)
        self.assertEqual(payload["image_commit"], self.task["image_commit"])
        self.assertEqual(payload["image_branch"], "ganges-7.6.0.6-stable")
        self.assertEqual(payload["nutest-py3-tests_branch"], "ganges-7.6-stable")
        self.assertEqual(payload["nutest-py3-tests_commit"], self.task["nutest-py3-tests_commit"])
        self.assertFalse(payload["skip_resource_spec_match"])
        self.assertTrue(payload["check_image_compatibility"])
        self.assertEqual(payload["label"], "SM_2008_P4-(3)-rerun")
        self.assertIn("jita3", payload["tester_tags"])
        self.assertEqual(payload["username"], "sudharshan.musali")
        self.assertEqual(payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]["gbn"], 1787129883)
        self.assertEqual(payload["test_framework_metadata"]["test"]["commit"], self.task["test_framework_metadata"]["test"]["commit"])
        self.assertEqual(payload["priority"], 10)
        self.assertEqual(payload["infra"][0]["entries"], ["Regression_cdp_special_config", "CDP_regression_ESXi_Qual"])
        self.assertEqual(payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]["entity"], "CONTAINER")

    def test_pc_override_preserves_nos_cluster(self):
        payload = self.build(self.task, self.tests, {
            "pc_branch": "master-pc",
            "pc_commit": "abc123",
            "pc_gbn": "99",
        }, "user")
        self.assertEqual(payload["resource_manager_json"]["NOS_CLUSTER"]["build"]["gbn"], 1786602592)
        self.assertEqual(payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]["branch"], "master-pc")
        self.assertEqual(payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]["gbn"], 99)
        self.assertNotIn("tag", payload["resource_manager_json"]["PRISM_CENTRAL"]["build"])
        self.assertNotIn("build_type", payload["resource_manager_json"]["PRISM_CENTRAL"]["build"])

    def test_commit_override_strips_illegal_rm_json_keys(self):
        self.task["resource_manager_json"]["NOS_CLUSTER"]["build"]["tag"] = "Latest Smoke Passed"
        self.task["resource_manager_json"]["NOS_CLUSTER"]["build"]["build_type"] = "release"
        self.task["resource_manager_json"]["PRISM_CENTRAL"]["build"]["tag"] = "Latest Smoke Passed"
        self.task["resource_manager_json"]["PRISM_CENTRAL"]["build"]["build_type"] = "opt"
        payload = self.build(self.task, self.tests, {
            "nos_branch": "ganges-7.6.0.6-stable",
            "nos_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "nos_gbn": "111",
            "pc_branch": "ganges-7.6.0.6-stable-pc",
            "pc_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "pc_gbn": "222",
        }, "user")
        nos_build = payload["resource_manager_json"]["NOS_CLUSTER"]["build"]
        pc_build = payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]
        self.assertEqual(nos_build["commit_id"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(nos_build["gbn"], 111)
        self.assertEqual(pc_build["commit_id"], "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        self.assertEqual(pc_build["gbn"], 222)
        self.assertNotIn("tag", nos_build)
        self.assertNotIn("build_type", nos_build)
        self.assertNotIn("tag", pc_build)
        self.assertNotIn("build_type", pc_build)

    def test_default_pool_kept_unless_override_checked(self):
        original = self.task["requested_hardware"]["infra"]
        payload = self.build(self.task, self.tests, {
            "resource_pool": "PoolA",
        }, "user")
        self.assertEqual(payload["infra"], original)
        payload = self.build(self.task, self.tests, {
            "override_pool": True,
            "resource_pool": "PoolA, PoolB",
        }, "user")
        self.assertEqual(payload["infra"], [{
            "kind": "ON_PREM",
            "type": "node_pool",
            "entries": ["PoolA", "PoolB"],
        }])

    def test_resource_pool_accepts_csv_and_keeps_kind(self):
        payload = self.build(self.task, self.tests, {
            "override_pool": True,
            "resource_pool": "PoolA, PoolB",
        }, "user")
        self.assertEqual(payload["infra"], [{
            "kind": "ON_PREM",
            "type": "node_pool",
            "entries": ["PoolA", "PoolB"],
        }])

    def test_smoke_tag_maps_to_latest_smoke_commit(self):
        payload = self.build(self.task, self.tests, {
            "nos_tag": "Latest Smoke Passed",
            "nos_branch": "master",
        }, "user")
        self.assertEqual(payload["commit_id"], "$LATEST_SMOKE_PASSED")
        self.assertEqual(payload["branch"], "master")


if __name__ == "__main__":
    unittest.main()
