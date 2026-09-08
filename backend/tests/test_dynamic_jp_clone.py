"""Unit tests for dynamic JP clone-to, retain defaults, and catalog test selection."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dynamic_jp_clone import (  # noqa: E402
    apply_clone_retain_exceptions,
    apply_destination_nos,
    apply_destination_pc,
    apply_latest_smoke_on_current_branches,
    apply_retain_setup_if_empty,
    aos_version_key,
    build_type_for_branch,
    catalog_test_to_row,
    clear_run_tests_with_tags,
    apply_clone_test_defaults,
    restore_clone_service,
    is_master_branch,
    nutest_mainline_branch,
    pc_branch_search_query,
    pick_exact_branch_name,
    retain_test_failure_is_filled,
    resolve_clone_pc_branch,
    select_catalog_test,
    set_sut_branch,
)


class TestNutestMainlineBranch(unittest.TestCase):
    def test_master_stays_master(self):
        self.assertEqual(nutest_mainline_branch("master"), "master")
        self.assertEqual(nutest_mainline_branch("Master"), "master")
        self.assertEqual(aos_version_key("master"), "master")

    def test_patch_lines_collapse_to_xy_mainline(self):
        self.assertEqual(nutest_mainline_branch("ganges-7.6.0.6-stable"), "ganges-7.6-stable")
        self.assertEqual(nutest_mainline_branch("7.6.0.6"), "ganges-7.6-stable")
        self.assertEqual(nutest_mainline_branch("ganges-7.5.1-stable"), "ganges-7.5-stable")
        self.assertEqual(nutest_mainline_branch("7.5.2"), "ganges-7.5-stable")
        self.assertEqual(nutest_mainline_branch("ganges-7.5.2-stable"), "ganges-7.5-stable")

    def test_already_mainline_unchanged(self):
        self.assertEqual(nutest_mainline_branch("ganges-7.6-stable"), "ganges-7.6-stable")
        self.assertEqual(nutest_mainline_branch("7.6"), "ganges-7.6-stable")
        self.assertEqual(nutest_mainline_branch("ganges-7.7-stable"), "ganges-7.7-stable")


class TestPcBranchResolution(unittest.TestCase):
    def test_master_uses_master_for_both_no_search(self):
        self.assertTrue(is_master_branch("master"))
        self.assertTrue(is_master_branch("Master"))
        self.assertIsNone(pc_branch_search_query("master"))
        pc, missing = resolve_clone_pc_branch("master", ["master-pc", "ganges-7.6-stable-pc"])
        self.assertEqual(pc, "master")
        self.assertIsNone(missing)

    def test_stable_requires_exact_pc_hit(self):
        self.assertEqual(pc_branch_search_query("ganges-7.6-stable"), "ganges-7.6-stable-pc")
        pc, missing = resolve_clone_pc_branch(
            "ganges-7.6-stable",
            ["ganges-7.6-stable", "ganges-7.6-stable-pc", "ganges-7.5-stable-pc"],
        )
        self.assertEqual(pc, "ganges-7.6-stable-pc")
        self.assertIsNone(missing)

    def test_missing_pc_branch_is_not_invented(self):
        pc, missing = resolve_clone_pc_branch("ganges-7.6-stable", ["ganges-7.6-stable", "master"])
        self.assertIsNone(pc)
        self.assertEqual(missing, "ganges-7.6-stable-pc")

    def test_pick_exact_preserves_jita_casing(self):
        self.assertEqual(
            pick_exact_branch_name(["Ganges-7.6-stable-pc"], "ganges-7.6-stable-pc"),
            "Ganges-7.6-stable-pc",
        )
        self.assertIsNone(pick_exact_branch_name(["ganges-7.6-stable-pc-extra"], "ganges-7.6-stable-pc"))


class TestBuildType(unittest.TestCase):
    def test_master_is_opt_else_release(self):
        self.assertEqual(build_type_for_branch("master"), "opt")
        self.assertEqual(build_type_for_branch("ganges-7.6-stable"), "release")


class TestDestinationBranches(unittest.TestCase):
    def test_master_from_release_jp_sets_opt(self):
        payload = {
            "git": {"branch": "ganges-7.6-stable", "repo": "main"},
            "build_selection": {"build_type": "release", "by_latest_smoked": True},
            "resource_manager_json": {
                "PRISM_CENTRAL": {
                    "build": {
                        "branch": "ganges-7.6-stable-pc",
                        "build_selection_build_type": "release",
                    }
                }
            },
            "system_under_test": {"product": "nos", "branch": "ganges-7.6-stable"},
        }
        apply_destination_nos(payload, "master")
        apply_destination_pc(payload, "master")
        set_sut_branch(payload, "master")
        self.assertEqual(payload["git"]["branch"], "master")
        self.assertEqual(payload["build_selection"]["build_type"], "opt")
        self.assertEqual(payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]["branch"], "master")
        self.assertEqual(
            payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]["build_selection_build_type"],
            "opt",
        )
        self.assertEqual(payload["system_under_test"]["branch"], "master")

    def test_pc_not_applied_when_unresolved(self):
        payload = {
            "git": {"branch": "old", "repo": "main"},
            "resource_manager_json": {
                "PRISM_CENTRAL": {"build": {"branch": "old-pc", "build_selection_build_type": "release"}}
            },
        }
        apply_destination_nos(payload, "ganges-7.6-stable")
        apply_destination_pc(payload, None)
        self.assertEqual(payload["git"]["branch"], "ganges-7.6-stable")
        self.assertEqual(payload["build_selection"]["build_type"], "release")
        self.assertEqual(
            payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]["branch"],
            "old-pc",
        )

    def test_latest_uses_destination_branches_already_on_payload(self):
        payload = {
            "git": {"branch": "master", "repo": "main"},
            "resource_manager_json": {
                "PRISM_CENTRAL": {"build": {"branch": "master"}}
            },
        }
        apply_latest_smoke_on_current_branches(payload)
        self.assertTrue(payload["build_selection"]["by_latest_smoked"])
        self.assertEqual(payload["build_selection"]["build_type"], "opt")
        pc = payload["resource_manager_json"]["PRISM_CENTRAL"]["build"]
        self.assertEqual(pc["branch"], "master")
        self.assertEqual(pc["build_selection_option"], "Latest Smoke Passed")
        self.assertEqual(pc["build_selection_build_type"], "opt")


class TestRetainDefaults(unittest.TestCase):
    def test_empty_gets_test_failure_and_data_corruption_error(self):
        payload = {}
        self.assertFalse(retain_test_failure_is_filled(payload))
        self.assertTrue(apply_retain_setup_if_empty(payload, duration_min=4320))
        tf = payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]
        self.assertEqual(tf["entity"], "DEPLOYMENT")
        self.assertEqual(tf["params"]["exceptions"], ["DataCorruptionError"])
        self.assertIn("Failed", tf["params"]["states_to_track"])

    def test_default_overwrites_empty_source_exceptions_with_data_corruption_error(self):
        payload = {
            "retain_resources_config": {
                "criteria": {
                    "TEST_FAILURE": {
                        "entity": "CONTAINER",
                        "type": "AFTER_EACH",
                        "params": {"duration": 60, "exceptions": [], "states_to_track": ["Failed"]},
                    }
                }
            }
        }
        self.assertTrue(retain_test_failure_is_filled(payload))
        self.assertTrue(apply_clone_retain_exceptions(payload, retain_setup_on_failure=False))
        tf = payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]
        self.assertEqual(tf["entity"], "CONTAINER")
        self.assertEqual(tf["params"]["exceptions"], ["DataCorruptionError"])

    def test_retain_setup_on_empty_payload_has_blank_exceptions(self):
        payload = {}
        self.assertTrue(apply_clone_retain_exceptions(payload, retain_setup_on_failure=True, duration_min=4320))
        tf = payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]
        self.assertEqual(tf["entity"], "DEPLOYMENT")
        self.assertEqual(tf["params"]["exceptions"], [])
        self.assertEqual(tf["params"]["duration"], 4320)

    def test_retain_setup_on_clears_exceptions(self):
        payload = {
            "retain_resources_config": {
                "criteria": {
                    "TEST_FAILURE": {
                        "entity": "DEPLOYMENT",
                        "type": "AFTER_EACH",
                        "params": {
                            "duration": 60,
                            "exceptions": ["DataCorruptionError"],
                            "states_to_track": ["Failed"],
                        },
                    }
                }
            }
        }
        self.assertTrue(apply_clone_retain_exceptions(payload, retain_setup_on_failure=True))
        tf = payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]
        self.assertEqual(tf["params"]["exceptions"], [])

    def test_migration_missing_test_failure_creates_block_with_dce(self):
        payload = {
            "emails": ["owner@nutanix.com"],
            "private": False,
            "advanced_options": {"skip_setup": True},
        }
        self.assertTrue(apply_clone_retain_exceptions(payload, retain_setup_on_failure=False))
        tf = payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]
        self.assertEqual(tf["entity"], "DEPLOYMENT")
        self.assertEqual(tf["params"]["exceptions"], ["DataCorruptionError"])
        self.assertEqual(payload["emails"], ["owner@nutanix.com"])
        self.assertFalse(payload["private"])
        self.assertTrue(payload["advanced_options"]["skip_setup"])

    def test_migration_overwrites_other_exceptions_with_dce(self):
        payload = {
            "retain_resources_config": {
                "criteria": {
                    "TEST_FAILURE": {
                        "entity": "DEPLOYMENT",
                        "type": "AFTER_EACH",
                        "params": {
                            "duration": 60,
                            "exceptions": ["TimeoutError"],
                            "states_to_track": ["Failed"],
                        },
                    }
                }
            }
        }
        self.assertTrue(apply_clone_retain_exceptions(payload, retain_setup_on_failure=False))
        tf = payload["retain_resources_config"]["criteria"]["TEST_FAILURE"]
        self.assertEqual(tf["params"]["exceptions"], ["DataCorruptionError"])


class TestCatalogSelect(unittest.TestCase):
    def test_prefers_nutest_over_services(self):
        hits = [
            {"name": "cdp.foo.test_bar", "framework": "services", "service": "NOS"},
            {"name": "cdp.foo.test_bar", "framework": "nutest-py3-tests", "service": "nutest-py3test"},
        ]
        hit = select_catalog_test(hits, "cdp.foo.test_bar")
        self.assertEqual(hit["framework"], "nutest-py3-tests")
        row = catalog_test_to_row(hit, "ganges-7.6-stable")
        self.assertEqual(row["framework"], "nutest-py3-tests")
        self.assertEqual(row["service"], "nutest-py3test")
        self.assertEqual(row["branch"], "ganges-7.6-stable")
        self.assertNotIn("_id", row)

    def test_uses_services_when_that_is_where_it_lives(self):
        hits = [
            {"name": "legacy.test_x", "framework": "services", "service": "NOS", "package_type": "tar"},
        ]
        hit = select_catalog_test(hits, "legacy.test_x")
        row = catalog_test_to_row(hit, "master")
        self.assertEqual(row["framework"], "services")
        self.assertEqual(row["service"], "NOS")
        self.assertEqual(row["branch"], "master")

    def test_unmatched_name_is_not_invented(self):
        self.assertIsNone(select_catalog_test(
            [{"name": "other.test", "framework": "nutest-py3-tests"}],
            "cdp.foo.test_bar",
        ))
        self.assertIsNone(catalog_test_to_row({}, "master"))


class TestClearRunTestsWithTags(unittest.TestCase):
    def test_toggle_off_keeps_only_allowlisted_additional_tags(self):
        jp = {
            "advanced_options": {
                "run_tests_with_tags": True,
                "tags": ["unstable"],
            },
            "run_tests_with_additional_tags": [
                "container__unlimited",
                "max_deployments__0",
                "infra__cdp",
                "752_rc1",
                "eg-7.6|RC3-july-13-2026",
            ],
            "tester_tags": ["jita3", "official", "752_rc1", "infra__cdp"],
            "emails": ["owner@nutanix.com"],
            "private": False,
        }
        self.assertTrue(clear_run_tests_with_tags(jp))
        self.assertFalse(jp["advanced_options"]["run_tests_with_tags"])
        self.assertEqual(jp["advanced_options"]["tags"], ["unstable"])
        self.assertEqual(
            jp["run_tests_with_additional_tags"],
            [
                "container__unlimited",
                "max_deployments__0",
                "infra__cdp",
            ],
        )
        self.assertEqual(jp["tester_tags"], ["official", "infra__cdp"])
        self.assertEqual(jp["emails"], ["owner@nutanix.com"])
        self.assertFalse(jp["private"])

    def test_toggle_already_off_keeps_allowlisted_only(self):
        jp = {
            "advanced_options": {"run_tests_with_tags": False, "skip_setup": True},
            "run_tests_with_additional_tags": ["jita3", "infra__cdp"],
            "tester_tags": ["jita3"],
        }
        self.assertTrue(clear_run_tests_with_tags(jp))
        self.assertFalse(jp["advanced_options"]["run_tests_with_tags"])
        self.assertTrue(jp["advanced_options"]["skip_setup"])
        self.assertEqual(jp["run_tests_with_additional_tags"], ["infra__cdp"])
        self.assertEqual(jp["tester_tags"], [])

    def test_subset_does_not_invent_allowlist(self):
        jp = {
            "advanced_options": {"run_tests_with_tags": True},
            "run_tests_with_additional_tags": ["jita3"],
            "tester_tags": ["jita3"],
        }
        clear_run_tests_with_tags(jp)
        self.assertEqual(jp["run_tests_with_additional_tags"], [])
        self.assertEqual(jp["tester_tags"], [])

    def test_empty_tag_lists_stay_empty(self):
        jp = {
            "advanced_options": {"run_tests_with_tags": True},
            "run_tests_with_additional_tags": [],
            "tester_tags": [],
        }
        clear_run_tests_with_tags(jp)
        self.assertFalse(jp["advanced_options"]["run_tests_with_tags"])
        self.assertEqual(jp["run_tests_with_additional_tags"], [])
        self.assertEqual(jp["tester_tags"], [])

    def test_missing_tag_fields_are_not_invented(self):
        jp = {
            "emails": ["keep@nutanix.com"],
            "private": True,
        }
        self.assertTrue(clear_run_tests_with_tags(jp))
        self.assertEqual(jp["advanced_options"], {"run_tests_with_tags": False})
        self.assertNotIn("run_tests_with_additional_tags", jp)
        self.assertNotIn("tester_tags", jp)
        self.assertEqual(jp["emails"], ["keep@nutanix.com"])
        self.assertTrue(jp["private"])

    def test_missing_advanced_options_gets_toggle_off(self):
        jp = {
            "emails": ["keep@nutanix.com"],
            "private": True,
            "run_tests_with_additional_tags": ["keep-me", "jita3"],
        }
        self.assertTrue(clear_run_tests_with_tags(jp))
        self.assertEqual(jp["advanced_options"], {"run_tests_with_tags": False})
        self.assertEqual(jp["run_tests_with_additional_tags"], [])
        self.assertNotIn("tester_tags", jp)
        self.assertEqual(jp["emails"], ["keep@nutanix.com"])
        self.assertTrue(jp["private"])

    def test_duplicates_and_mixed_case(self):
        jp = {
            "advanced_options": {"run_tests_with_tags": True},
            "run_tests_with_additional_tags": [
                "Infra__cdp",
                "infra__cdp",
                "INFRA__CDP",
                "max_deployments__0",
            ],
            "tester_tags": ["INFRA__CDP", "infra__cdp"],
        }
        clear_run_tests_with_tags(jp)
        self.assertEqual(jp["run_tests_with_additional_tags"], ["Infra__cdp", "max_deployments__0"])
        self.assertEqual(jp["tester_tags"], ["INFRA__CDP"])

    def test_whitespace_and_empty_entries(self):
        jp = {
            "advanced_options": {"run_tests_with_tags": True},
            "run_tests_with_additional_tags": ["  jita3  ", "", "  ", "752_rc1"],
            "tester_tags": [" infra__cdp ", None, "official"],
        }
        clear_run_tests_with_tags(jp)
        self.assertEqual(jp["run_tests_with_additional_tags"], [])
        self.assertEqual(jp["tester_tags"], ["infra__cdp", "official"])

    def test_official_stays_on_tester_tags_not_additional(self):
        jp = {
            "advanced_options": {"run_tests_with_tags": True},
            "run_tests_with_additional_tags": ["official", "jita3", "752_rc1"],
            "tester_tags": ["official", "752_rc1"],
        }
        clear_run_tests_with_tags(jp)
        self.assertEqual(jp["run_tests_with_additional_tags"], [])
        self.assertEqual(jp["tester_tags"], ["official"])

    def test_comma_separated_string_tags(self):
        jp = {
            "advanced_options": {"run_tests_with_tags": True, "skip_setup": True},
            "run_tests_with_additional_tags": (
                "container__unlimited, jita3, 752_rc1, infra__cdp, max_deployments__0"
            ),
            "tester_tags": "jita3, official, 752_rc1, infra__cdp",
            "emails": ["owner@nutanix.com"],
            "private": False,
        }
        clear_run_tests_with_tags(jp)
        self.assertFalse(jp["advanced_options"]["run_tests_with_tags"])
        self.assertTrue(jp["advanced_options"]["skip_setup"])
        self.assertEqual(
            jp["run_tests_with_additional_tags"],
            ["container__unlimited", "infra__cdp", "max_deployments__0"],
        )
        self.assertEqual(jp["tester_tags"], ["official", "infra__cdp"])
        self.assertEqual(jp["emails"], ["owner@nutanix.com"])

    def test_post_then_put_refilters_restored_run_tags(self):
        jp = {
            "advanced_options": {"run_tests_with_tags": True, "tags": ["unstable"]},
            "run_tests_with_additional_tags": ["jita3", "infra__cdp", "752_rc1"],
            "tester_tags": ["jita3", "752_rc1"],
            "emails": ["owner@nutanix.com"],
            "private": False,
        }
        clear_run_tests_with_tags(jp)
        jp["tester_tags"] = list(dict.fromkeys(jp["tester_tags"] + ["official"]))
        self.assertFalse(jp["advanced_options"]["run_tests_with_tags"])
        self.assertEqual(jp["run_tests_with_additional_tags"], ["infra__cdp"])
        self.assertEqual(jp["tester_tags"], ["official"])

        # JITA GET reintroduces run tags (POST ignored).
        jp["advanced_options"]["run_tests_with_tags"] = True
        jp["run_tests_with_additional_tags"] = ["jita3", "infra__cdp", "752_rc1"]
        jp["tester_tags"] = ["jita3", "official", "752_rc1"]
        jp["tester_tags"] = list(dict.fromkeys(jp["tester_tags"] + ["official"]))
        clear_run_tests_with_tags(jp)
        self.assertFalse(jp["advanced_options"]["run_tests_with_tags"])
        self.assertEqual(jp["advanced_options"]["tags"], ["unstable"])
        self.assertEqual(jp["run_tests_with_additional_tags"], ["infra__cdp"])
        self.assertEqual(jp["tester_tags"], ["official"])
        self.assertEqual(jp["emails"], ["owner@nutanix.com"])
        self.assertFalse(jp["private"])

    def test_non_dict_is_a_no_op(self):
        self.assertFalse(clear_run_tests_with_tags(None))
        self.assertFalse(clear_run_tests_with_tags("jp"))


class TestCloneTestDefaults(unittest.TestCase):
    def test_empty_payload_sets_nutest_and_skip_bad_tests(self):
        jp = {}
        self.assertTrue(apply_clone_test_defaults(jp))
        self.assertEqual(jp["test_service"], "NutestPy3Tests")
        self.assertTrue(jp["skip_bad_tests"])
        self.assertNotIn("service", jp)

    def test_overwrites_other_or_empty_test_service(self):
        jp = {"test_service": "CustomTest", "skip_bad_tests": False}
        apply_clone_test_defaults(jp)
        self.assertEqual(jp["test_service"], "NutestPy3Tests")
        self.assertTrue(jp["skip_bad_tests"])
        jp2 = {"test_service": "  ", "skip_bad_tests": False}
        apply_clone_test_defaults(jp2)
        self.assertEqual(jp2["test_service"], "NutestPy3Tests")
        self.assertTrue(jp2["skip_bad_tests"])

    def test_does_not_touch_service_or_services(self):
        jp = {
            "sync_to_tcms": True,
            "service": "nutest-py3test",
            "services": ["NOS"],
            "test_service": "Nutest",
            "skip_bad_tests": False,
        }
        apply_clone_test_defaults(jp)
        self.assertEqual(jp["service"], "nutest-py3test")
        self.assertEqual(jp["services"], ["NOS"])
        self.assertEqual(jp["test_service"], "NutestPy3Tests")
        self.assertTrue(jp["skip_bad_tests"])

    def test_does_not_fill_service_when_tcms_off_and_blank(self):
        jp = {"sync_to_tcms": False, "service": "", "test_service": "Nutest"}
        apply_clone_test_defaults(jp)
        self.assertEqual(jp["service"], "")
        self.assertEqual(jp["test_service"], "NutestPy3Tests")

    def test_does_not_touch_email_or_private(self):
        jp = {
            "service": "nutest-py3test",
            "test_service": "NOS",
            "skip_bad_tests": False,
            "emails": ["owner@nutanix.com"],
            "private": False,
        }
        apply_clone_test_defaults(jp)
        self.assertEqual(jp["service"], "nutest-py3test")
        self.assertEqual(jp["test_service"], "NutestPy3Tests")
        self.assertTrue(jp["skip_bad_tests"])
        self.assertEqual(jp["emails"], ["owner@nutanix.com"])
        self.assertFalse(jp["private"])

    def test_non_dict_is_a_no_op(self):
        self.assertFalse(apply_clone_test_defaults(None))
        self.assertFalse(apply_clone_test_defaults("jp"))


class TestRestoreCloneService(unittest.TestCase):
    def test_restores_source_service_and_services_after_tcms_overwrite(self):
        source = {"service": "NOS", "services": ["NOS", "PC"]}
        jp = {
            "service": "NutestPy3Tests",
            "services": ["nutest-py3test"],
            "test_service": "NutestPy3Tests",
        }
        self.assertTrue(restore_clone_service(jp, source))
        self.assertEqual(jp["service"], "NOS")
        self.assertEqual(jp["services"], ["NOS", "PC"])
        self.assertEqual(jp["test_service"], "NutestPy3Tests")

    def test_missing_source_keys_are_left_alone(self):
        jp = {"service": "NutestPy3Tests", "test_service": "NutestPy3Tests"}
        restore_clone_service(jp, {"name": "src"})
        self.assertEqual(jp["service"], "NutestPy3Tests")
        self.assertNotIn("services", jp)

    def test_non_dict_is_a_no_op(self):
        self.assertFalse(restore_clone_service(None, {}))
        self.assertFalse(restore_clone_service({}, None))


if __name__ == "__main__":
    unittest.main()
