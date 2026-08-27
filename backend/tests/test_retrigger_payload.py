"""Unit tests for Jita rerun payload construction."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_builder():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _summarize_jita_resource_config(")
    mid = src.index("def _rewrite_url_for_new_build(")
    end = src.index("\n# ======================================================\n# Testcase Management")
    # Skip Flask routes between summarize and rewrite helpers.
    chunk = src[start:src.index("@app.route(\"/mcp/regression/failed-analysis/retrigger-preview\"")] + src[mid:end]
    ns = {}
    exec(chunk, ns)  # noqa: S102
    return ns


class RetriggerPayloadTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load_builder()
        self.build = self.ns["_build_rerun_payload"]
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
                "hypervisor": "esx",
                "hypervisor_version": "branch_symlink",
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

    def test_summarize_physical_node_pool(self):
        summary = self.ns["_summarize_jita_resource_config"](self.task)
        self.assertEqual(summary["resources"], "By Node Pool")
        self.assertEqual(summary["resource_type"], "Physical")
        self.assertEqual(summary["node_pools"], [
            "Regression_cdp_special_config",
            "CDP_regression_ESXi_Qual",
        ])
        self.assertTrue(summary["match_resource_spec"])
        self.assertEqual(summary["hypervisor"], "esx")
        self.assertEqual(summary["nos_branch"], "ganges-7.6.0.6-stable")
        self.assertEqual(summary["resources_mode"], "node_pool")
        self.assertEqual(summary["resource_type_key"], "physical")

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
        self.assertNotIn("nutest-py3-tests_commit", payload)
        self.assertFalse(payload["skip_resource_spec_match"])
        self.assertTrue(payload["check_image_compatibility"])
        self.assertEqual(payload["label"], "SM_2008_P4-(3)-rerun")
        self.assertIn("jita3", payload["tester_tags"])
        self.assertEqual(payload["username"], "sudharshan.musali")
        self.assertEqual(payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]["gbn"], 1787129883)
        self.assertNotIn("commit", payload["test_framework_metadata"]["test"])
        self.assertNotIn("commit", payload["test_framework_metadata"]["framework"])
        self.assertEqual(payload["priority"], 10)
        self.assertEqual(payload["infra"][0]["entries"], ["Regression_cdp_special_config", "CDP_regression_ESXi_Qual"])
        self.assertEqual(payload["requested_hardware"]["infra"], payload["infra"])
        self.assertEqual(payload["requested_hardware"]["hypervisor"], "esx")
        self.assertNotIn("nested_params", payload["requested_hardware"])
        self.assertEqual(payload["hypervisor"], "esx")
        self.assertEqual(payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]["entity"], "CONTAINER")
        self.assertEqual(
            payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]["params"]["duration"],
            4320,
        )

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
        self.task["requested_hardware"]["infra"][0]["params"] = {"foo": 1}
        payload = self.build(self.task, self.tests, {
            "override_pool": True,
            "resource_pool": "PoolA, PoolB",
        }, "user")
        self.assertEqual(payload["infra"][0]["kind"], "ON_PREM")
        self.assertEqual(payload["infra"][0]["type"], "node_pool")
        self.assertEqual(payload["infra"][0]["entries"], ["PoolA", "PoolB"])
        self.assertEqual(payload["infra"][0]["params"], {"foo": 1})
        self.assertEqual(payload["requested_hardware"]["infra"], payload["infra"])
        self.assertEqual(payload["requested_hardware"]["hypervisor"], "esx")

    def test_smoke_tag_maps_to_latest_smoke_commit(self):
        payload = self.build(self.task, self.tests, {
            "nos_tag": "Latest Smoke Passed",
            "nos_branch": "master",
        }, "user")
        self.assertEqual(payload["commit_id"], "$LATEST_SMOKE_PASSED")
        self.assertEqual(payload["branch"], "master")

    def test_commit_only_override_keeps_original_branch_label_tags_retain(self):
        """UI no longer sends NOS branch/label/tags/scheduling; backend must copy them."""
        payload = self.build(self.task, self.tests, {
            "nos_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "nos_gbn": "111",
            "pc_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "pc_gbn": "222",
        }, "user")
        self.assertEqual(payload["branch"], self.task["branch"])
        self.assertEqual(payload["commit_id"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(payload["gbn"], 111)
        self.assertEqual(payload["label"], "SM_2008_P4-(3)-rerun")
        self.assertEqual(payload["tester_tags"], ["jita3", "v3.1", "infra__cdp"])
        self.assertFalse(payload["skip_resource_spec_match"])
        self.assertTrue(payload["check_image_compatibility"])
        self.assertEqual(payload["priority"], 10)
        self.assertEqual(
            payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]["entity"],
            "CONTAINER",
        )
        nos_build = payload["resource_manager_json"]["NOS_CLUSTER"]["build"]
        self.assertEqual(nos_build["branch"], "ganges-7.6.0.6-stable")
        self.assertEqual(nos_build["commit_id"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        pc_build = payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]
        self.assertEqual(pc_build["branch"], "ganges-7.6.0.6-stable-pc")
        self.assertEqual(pc_build["commit_id"], "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    def test_pc_build_urls_map_to_jita_rm_json(self):
        """Jita PC tab: Build Url -> nos_build_url, Build QCOW2 URL -> pc_build_url."""
        payload = self.build(self.task, self.tests, {
            "pc_gbn": "1787527971",
            "pc_build_url": "http://vendor.dyn.nutanix.com/builds-pc-builds/master/opt/",
            "pc_build_url_qcow2": "http://vendor.dyn.nutanix.com/builds-pc-builds/master/publish_pc_image_internal/",
        }, "user")
        pc_build = payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]
        self.assertEqual(pc_build["gbn"], 1787527971)
        self.assertEqual(
            pc_build["nos_build_url"],
            "http://vendor.dyn.nutanix.com/builds-pc-builds/master/opt/",
        )
        self.assertEqual(
            pc_build["pc_build_url"],
            "http://vendor.dyn.nutanix.com/builds-pc-builds/master/publish_pc_image_internal/",
        )

    def test_pc_commit_override_drops_stale_urls_unless_provided(self):
        self.task["resource_manager_json"]["PRISM_CENTRAL"]["build"]["nos_build_url"] = "http://old/opt/"
        self.task["resource_manager_json"]["PRISM_CENTRAL"]["build"]["pc_build_url"] = "http://old/qcow2/"
        payload = self.build(self.task, self.tests, {
            "pc_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "pc_gbn": "222",
        }, "user")
        pc_build = payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]
        self.assertNotIn("nos_build_url", pc_build)
        self.assertNotIn("pc_build_url", pc_build)

    def test_nos_commit_keeps_original_jita_branch(self):
        payload = self.build(self.task, self.tests, {
            "nos_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "nos_gbn": "111",
        }, "user")
        self.assertEqual(payload["branch"], self.task["branch"])
        self.assertEqual(payload["commit_id"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(payload["gbn"], 111)
        self.assertEqual(
            payload["resource_manager_json"]["NOS_CLUSTER"]["build"]["branch"],
            self.task["branch"],
        )

    def test_image_follows_nos_when_jp_used_same_branch(self):
        """Screenshot case: Image branch/commit/GBN match NOS on the original JP."""
        self.assertEqual(self.task["image_branch"], self.task["branch"])
        self.assertEqual(self.task["image_commit"], self.task["commit_id"])
        self.assertEqual(self.task["image_gbn"], self.task["gbn"])
        payload = self.build(self.task, self.tests, {
            "nos_commit": "ad335223f98b4805b362e475c633c3460bc3494",
            "nos_gbn": "1785774528",
            "nos_branch": "pangeas-7.6.0.6-stable",
        }, "user")
        self.assertEqual(payload["branch"], "pangeas-7.6.0.6-stable")
        self.assertEqual(payload["commit_id"], "ad335223f98b4805b362e475c633c3460bc3494")
        self.assertEqual(payload["gbn"], 1785774528)
        self.assertEqual(payload["image_branch"], payload["branch"])
        self.assertEqual(payload["image_commit"], payload["commit_id"])
        self.assertEqual(payload["image_gbn"], payload["gbn"])

    def test_unchecked_image_uses_new_nos_commit_when_image_branch_missing(self):
        """Jita often omits image_branch; matching original image commit still follows NOS."""
        self.task.pop("image_branch", None)
        old_image = self.task["image_commit"]
        payload = self.build(self.task, self.tests, {
            "nos_commit": "ad335223f98b4805b362e475c633c3460bc3494",
            "nos_gbn": "1785774528",
        }, "user")
        self.assertEqual(payload["commit_id"], "ad335223f98b4805b362e475c633c3460bc3494")
        self.assertEqual(payload["image_commit"], "ad335223f98b4805b362e475c633c3460bc3494")
        self.assertEqual(payload["image_gbn"], 1785774528)
        self.assertNotEqual(payload["image_commit"], old_image)

    def test_image_kept_when_branch_differs_from_nos(self):
        self.task["image_branch"] = "hypervisor-other-branch"
        self.task["image_commit"] = "oldimagecommit"
        self.task["image_gbn"] = 111
        payload = self.build(self.task, self.tests, {
            "nos_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "nos_gbn": "222",
            "nos_branch": "master",
        }, "user")
        self.assertEqual(payload["branch"], "master")
        self.assertEqual(payload["image_branch"], "hypervisor-other-branch")
        self.assertEqual(payload["image_commit"], "oldimagecommit")
        self.assertEqual(payload["image_gbn"], 111)

    def test_explicit_image_override_wins(self):
        payload = self.build(self.task, self.tests, {
            "nos_branch": "master",
            "nos_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "nos_gbn": "222",
            "image_branch": "custom-image-branch",
            "image_commit": "customimagecommit",
            "image_gbn": "333",
        }, "user")
        self.assertEqual(payload["branch"], "master")
        self.assertEqual(payload["image_branch"], "custom-image-branch")
        self.assertEqual(payload["image_commit"], "customimagecommit")
        self.assertEqual(payload["image_gbn"], 333)

    def test_copies_original_tar_nos_url_and_rewrites_gbn(self):
        self.task["build_type"] = "release"
        self.task["requested_hardware"]["imaging_options"] = {
            "nos_url": "http://vendor.dyn.nutanix.com/builds/nos/1786602592/nutanix_installer_package.tar.gz",
            "hypervisor_url": "http://vendor.dyn.nutanix.com/builds/ahv/1786602592/ahv.qcow2",
            "enable_large_partitions": True,
        }
        payload = self.build(self.task, self.tests, {
            "nos_commit": "ad335223f98b4805b362e475c633c3460bc3494",
            "nos_gbn": "1785774528",
            "nos_branch": "pangeas-7.6.0.6-stable",
        }, "user")
        self.assertEqual(payload["build_type"], "release")
        self.assertEqual(
            payload["imaging_options"]["nos_url"],
            "http://vendor.dyn.nutanix.com/builds/nos/1785774528/nutanix_installer_package.tar.gz",
        )
        self.assertEqual(
            payload["imaging_options"]["hypervisor_url"],
            "http://vendor.dyn.nutanix.com/builds/ahv/1785774528/ahv.qcow2",
        )
        self.assertTrue(payload["imaging_options"]["enable_large_partitions"])
        self.assertIn(".tar.gz", payload["imaging_options"]["nos_url"])

    def test_infers_release_build_type_from_original_tar_url(self):
        self.task["requested_hardware"]["imaging_options"] = {
            "nos_url": "http://example/aos-el8.x86_64.tar.gz",
        }
        payload = self.build(self.task, self.tests, {
            "nos_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "nos_gbn": "222",
        }, "user")
        self.assertEqual(payload["build_type"], "release")
        self.assertTrue(payload["imaging_options"]["nos_url"].endswith(".tar.gz"))

    def test_copies_nested_ahv_2_params(self):
        self.task["requested_hardware"]["nested_params"] = {
            "is_nested": True,
            "version": "2.0",
        }
        payload = self.build(self.task, self.tests, {
            "nos_commit": "158a71724a2cefedffbb413ccb8a1287830f4543",
            "nos_gbn": "1787416010",
            "nos_branch": "ganges-7.6.0.6-stable",
        }, "user")
        self.assertEqual(payload["nested_params"]["version"], "2.0")
        self.assertTrue(payload["nested_params"]["is_nested"])

    def test_jp_name_does_not_invent_nested_params(self):
        self.task["label"] = "CDP_Regression_FullReg_7.6.X_NHAV2.0_AOS-tar-(3)"
        payload = self.build(self.task, self.tests, {
            "nos_commit": "158a71724a2cefedffbb413ccb8a1287830f4543",
            "nos_gbn": "1787416010",
        }, "user")
        self.assertNotIn("nested_params", payload)

    def test_physical_jp_has_no_nested_params(self):
        payload = self.build(self.task, self.tests, {
            "nos_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "nos_gbn": "222",
        }, "user")
        self.assertNotIn("nested_params", payload)

    def test_resource_requirement_overrides_match_jita_form(self):
        payload = self.build(self.task, self.tests, {
            "override_resource_config": True,
            "resources_mode": "node_pool",
            "resource_type": "nested_2.0",
            "node_pools": ["CDP_regression_ESXi_Qual"],
            "hypervisor": "kvm",
            "match_resource_spec": False,
        }, "user")
        self.assertEqual(payload["infra"][0]["type"], "node_pool")
        self.assertEqual(payload["infra"][0]["entries"], ["CDP_regression_ESXi_Qual"])
        self.assertEqual(payload["requested_hardware"]["infra"], payload["infra"])
        self.assertEqual(payload["requested_hardware"]["hypervisor"], "kvm")
        self.assertEqual(payload["hypervisor"], "kvm")
        self.assertEqual(payload["nested_params"]["version"], "2.0")
        self.assertEqual(payload["requested_hardware"]["nested_params"]["version"], "2.0")
        self.assertTrue(payload["skip_resource_spec_match"])

    def test_resource_requirement_physical_clears_nested_params(self):
        self.task["requested_hardware"]["nested_params"] = {
            "is_nested": True,
            "version": "2.0",
        }
        payload = self.build(self.task, self.tests, {
            "override_resource_config": True,
            "resources_mode": "node_pool",
            "resource_type": "physical",
            "node_pools": ["Regression_cdp_special_config"],
            "hypervisor": "esx",
            "match_resource_spec": True,
        }, "user")
        self.assertNotIn("nested_params", payload)
        self.assertNotIn("nested_params", payload["requested_hardware"])
        self.assertFalse(payload["skip_resource_spec_match"])
        self.assertEqual(payload["infra"][0]["entries"], ["Regression_cdp_special_config"])

    def test_framework_branch_override_clears_commits_by_default(self):
        payload = self.build(self.task, self.tests, {
            "nutest_branch": "ganges-7.6-stable",
            "test_branch": "ganges-7.6-stable",
        }, "user")
        tfm = payload["test_framework_metadata"]
        self.assertEqual(tfm["framework"]["branch"], "ganges-7.6-stable")
        self.assertEqual(tfm["test"]["branch"], "ganges-7.6-stable")
        self.assertNotIn("commit", tfm["framework"])
        self.assertNotIn("commit", tfm["test"])
        self.assertEqual(payload["nutest-py3-tests_branch"], "ganges-7.6-stable")
        self.assertNotIn("nutest-py3-tests_commit", payload)

    def test_framework_commits_pass_through_only_when_user_sends_them(self):
        payload = self.build(self.task, self.tests, {
            "nutest_branch": "ganges-7.6-stable",
            "test_branch": "ganges-7.6-stable",
            "nutest_commit": "cccccccccccccccccccccccccccccccccccccccc",
            "test_commit": "dddddddddddddddddddddddddddddddddddddddd",
        }, "user")
        tfm = payload["test_framework_metadata"]
        self.assertEqual(tfm["framework"]["commit"], "cccccccccccccccccccccccccccccccccccccccc")
        self.assertEqual(tfm["test"]["commit"], "dddddddddddddddddddddddddddddddddddddddd")
        self.assertEqual(payload["nutest-py3-tests_commit"], "cccccccccccccccccccccccccccccccccccccccc")

    def test_label_priority_tags_and_scheduling_pass_through(self):
        payload = self.build(self.task, self.tests, {
            "label": "manual-rerun",
            "priority": "7",
            "tester_tags": "cdp, nightly",
            "skip_resource_spec_match": True,
            "check_image_compatibility": False,
        }, "user")
        self.assertEqual(payload["label"], "manual-rerun")
        self.assertEqual(payload["priority"], 7)
        self.assertEqual(payload["tester_tags"], ["cdp", "nightly", "jita3"])
        self.assertTrue(payload["skip_resource_spec_match"])
        self.assertFalse(payload["check_image_compatibility"])
        self.assertEqual(
            payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]["entity"],
            "CONTAINER",
        )
        self.assertEqual(
            payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]["params"]["duration"],
            4320,
        )

    def test_rerun_always_sets_retain_to_72_hours(self):
        payload = self.build(self.task, self.tests, {
            "retain_on_failure": True,
            "retain_duration": "60",
        }, "user")
        self.assertEqual(
            payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]["params"]["duration"],
            72 * 60,
        )
        self.assertEqual(
            payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]["entity"],
            "CONTAINER",
        )


class RetriggerAccountTests(unittest.TestCase):
    def setUp(self):
        ns = _load_builder()
        self.jp_name = ns["_jp_name_from_agave_task"]
        self.is_esx = ns["_is_esx_job_profile"]
        self.account = ns["_rerun_trigger_account"]

    def test_jp_name_prefers_explicit_field(self):
        self.assertEqual(
            self.jp_name({"job_profile_name": "CDP_ESXi_Qual", "label": "Other-(1)"}),
            "CDP_ESXi_Qual",
        )

    def test_jp_name_from_nested_job_profile(self):
        self.assertEqual(
            self.jp_name({"job_profile": {"name": "AHV_Nested_Smoke"}}),
            "AHV_Nested_Smoke",
        )

    def test_jp_name_strips_rerun_count_from_label(self):
        self.assertEqual(self.jp_name({"label": "CDP_regression_ESXi_Qual-(3)"}), "CDP_regression_ESXi_Qual")

    def test_esx_jp_uses_teamchandra(self):
        self.assertTrue(self.is_esx("CDP_regression_ESXi_Qual"))
        self.assertEqual(self.account("CDP_regression_ESXi_Qual"), "svc.teamchandra")
        self.assertEqual(self.account("master_esx_full_reg"), "svc.teamchandra")

    def test_non_esx_jp_uses_ldap(self):
        self.assertFalse(self.is_esx("SM_2008_P4"))
        self.assertIsNone(self.account("SM_2008_P4"))
        self.assertIsNone(self.account(""))

    def test_ahv_or_esx_name_uses_suffix(self):
        ahv_suffix = "AHVorESX_special_config_AOS-tar_(AHV)"
        esx_suffix = "AHVorESX_special_config_AOS-tar_(ESX)"
        esxi_suffix = "AHVorESX_special_config_AOS-tar_(ESXi)"
        self.assertFalse(self.is_esx(ahv_suffix))
        self.assertIsNone(self.account(ahv_suffix))
        self.assertTrue(self.is_esx(esx_suffix))
        self.assertEqual(self.account(esx_suffix), "svc.teamchandra")
        self.assertTrue(self.is_esx(esxi_suffix))
        self.assertEqual(self.account(esxi_suffix), "svc.teamchandra")
        self.assertFalse(self.is_esx("CDP_AHV_Nested_Smoke"))

    def test_mixed_batch_picks_account_per_jp(self):
        ns = _load_builder()
        resolve = ns["_resolve_rerun_jp_name"]
        select = ns["_select_rerun_auth"]
        accounts = {"svc.teamchandra": ("svc.teamchandra", "esx-secret")}
        ldap = ("alice", "ldap-secret")
        fetched = {
            "jp-esx": "CDP_regression_ESXi_Qual",
            "jp-ahv": "CDP_AHV_Nested_Smoke",
        }
        cache = {}

        esx_task = {
            "label": "Generic_Label-(1)",
            "job_profile": {"$oid": "jp-esx"},
        }
        ahv_task = {
            "label": "CDP_regression_ESXi_Qual-(9)",
            "job_profile_name": "CDP_AHV_Nested_Smoke",
            "job_profile": {"$oid": "jp-ahv"},
        }

        esx_name = resolve(esx_task, fetch_name=fetched.get, cache=cache)
        ahv_name = resolve(ahv_task, fetch_name=fetched.get, cache=cache)
        esx_auth, esx_user = select(esx_name, ldap, "alice", accounts)
        ahv_auth, ahv_user = select(ahv_name, ldap, "alice", accounts)

        self.assertEqual(esx_name, "CDP_regression_ESXi_Qual")
        self.assertEqual(esx_user, "svc.teamchandra")
        self.assertEqual(esx_auth, accounts["svc.teamchandra"])
        self.assertEqual(ahv_name, "CDP_AHV_Nested_Smoke")
        self.assertEqual(ahv_user, "alice")
        self.assertEqual(ahv_auth, ldap)

    def test_jp_fetch_is_cached_across_tasks(self):
        ns = _load_builder()
        resolve = ns["_resolve_rerun_jp_name"]
        calls = []

        def fetch_name(jp_id):
            calls.append(jp_id)
            return "CDP_ESXi_Qual"

        cache = {}
        task = {"job_profile": {"$oid": "jp-1"}, "label": "Other-(1)"}
        self.assertEqual(resolve(task, fetch_name=fetch_name, cache=cache), "CDP_ESXi_Qual")
        self.assertEqual(resolve(task, fetch_name=fetch_name, cache=cache), "CDP_ESXi_Qual")
        self.assertEqual(calls, ["jp-1"])

    def test_nos_override_resolution_does_not_leak_between_tasks(self):
        first = {"nos_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
        second = dict(first)
        first["nos_branch"] = "esx-resolved-branch"
        self.assertNotIn("nos_branch", second)


if __name__ == "__main__":
    unittest.main()
