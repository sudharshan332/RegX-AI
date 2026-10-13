"""Unit tests for dynamic JP clone-to, retain defaults, and catalog test selection."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dynamic_jp_clone import (  # noqa: E402
    apply_clone_patch_fields,
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
    clone_target_block,
    collect_clone_test_set_ids,
    gerrit_patch_branch,
    plan_source_test_set_links,
    resolve_clone_patches,
    restore_clone_patch_tags,
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


def _official_jp_77():
    """Official 7.7 JP with several test-set shapes and both patch sides."""
    test_patch = (
        "https://nugerrit.ntnxdpro.com/changes/"
        "nutest-py3-tests~ganges-7.7-stable~I111/patch?zip"
    )
    fw_patch = (
        "https://nugerrit.ntnxdpro.com/changes/"
        "nutest-py3~ganges-7.7-stable~I222/patch?zip"
    )
    return {
        "name": "CDP_Regression_FullReg_7.7_Official",
        "test_sets": [
            {"$oid": "a" * 24},
            {"_id": {"$oid": "b" * 24}},
            "c" * 24,
            {"id": "e" * 24, "name": "extra-by-id"},
        ],
        "test_set": {"name": "legacy-only", "path": "test_sets/milestones/7.7/legacy"},
        "test_framework_metadata": {
            "test": {"branch": "ganges-7.7-stable", "commit": "abc", "patch_url": test_patch},
            "framework": {"branch": "ganges-7.7-stable", "commit": "def", "patch_url": fw_patch},
        },
        "patch_url": fw_patch,
        "tester_tags": [
            "official",
            "infra__cdp",
            "patch_url__" + test_patch,
            "framework_patch_url__" + fw_patch,
            "752_rc1",
        ],
        "nutest-py3-tests_branch": "ganges-7.7-stable",
    }, test_patch, fw_patch


class TestCloneTestSetLinks(unittest.TestCase):
    def test_77_to_761_links_every_testset_shape(self):
        source, _test_patch, _fw_patch = _official_jp_77()
        # Legacy singular ref is ignored while test_sets is populated, and it has
        # no id — it must be reported, not silently attached as a fake id.
        source["test_sets"].append({"name": "missing-id-set"})
        plan = plan_source_test_set_links(source)
        self.assertEqual(plan["ids"], ["a" * 24, "b" * 24, "c" * 24, "e" * 24])
        self.assertEqual(plan["unresolved"], ["missing-id-set"])
        self.assertTrue(any("missing-id-set" in w for w in plan["warnings"]))

    def test_empty_test_sets_falls_back_to_every_legacy_ref(self):
        source = {
            "test_sets": [],
            "test_set": [
                {"$oid": "1" * 24},
                {"_id": "2" * 24},
                {"name": "no-id"},
            ],
        }
        ids, unresolved = collect_clone_test_set_ids(source)
        self.assertEqual(ids, ["1" * 24, "2" * 24])
        self.assertEqual(unresolved, ["no-id"])

    def test_duplicate_ids_kept_once_in_source_order(self):
        source = {
            "test_sets": [
                {"$oid": "A" * 24},
                {"$oid": "a" * 24},
                "b" * 24,
            ]
        }
        ids, unresolved = collect_clone_test_set_ids(source)
        self.assertEqual(ids, ["A" * 24, "b" * 24])
        self.assertEqual(unresolved, [])

    def test_explicit_selection_does_not_pull_the_rest(self):
        source, _, _ = _official_jp_77()
        plan = plan_source_test_set_links(source, explicit_id="only-this")
        self.assertEqual(plan["ids"], ["only-this"])
        self.assertEqual(plan["warnings"], [])

    def test_other_versions_use_the_same_full_list(self):
        source = {
            "name": "CDP_Regression_7.5_Official",
            "test_sets": [{"$oid": "a" * 24}, {"$oid": "b" * 24}, {"$oid": "c" * 24}],
        }
        plan = plan_source_test_set_links(source)
        self.assertEqual(len(plan["ids"]), 3)


class TestClonePatches(unittest.TestCase):
    def test_gerrit_branch_from_patch_url(self):
        url = (
            "https://nugerrit.ntnxdpro.com/changes/"
            "nutest-py3-tests~ganges-7.7-stable~Iabc/patch?zip"
        )
        self.assertEqual(gerrit_patch_branch(url), "ganges-7.7-stable")
        self.assertEqual(gerrit_patch_branch("https://example.com/patch.zip"), "")

    def test_77_to_761_reports_incompatible_patches_instead_of_keeping_them(self):
        source, test_patch, fw_patch = _official_jp_77()
        payload = {
            "test_framework_metadata": source["test_framework_metadata"],
            "patch_url": source["patch_url"],
            "tester_tags": list(source["tester_tags"]),
        }
        test_kept, fw_kept, warnings = resolve_clone_patches(source, "ganges-7.6.1-stable")
        self.assertIsNone(test_kept)
        self.assertIsNone(fw_kept)
        self.assertEqual(len(warnings), 2)
        self.assertIn(test_patch, warnings[0])
        self.assertIn("ganges-7.7-stable", warnings[0])
        self.assertIn("ganges-7.6.1-stable", warnings[0])
        self.assertIn(fw_patch, warnings[1])
        apply_clone_patch_fields(payload, "ganges-7.6.1-stable", test_kept, fw_kept)
        clear_run_tests_with_tags(payload)
        restore_clone_patch_tags(payload, source, test_kept, fw_kept)
        self.assertNotIn("patch_url", payload["test_framework_metadata"]["test"])
        self.assertNotIn("patch_url", payload["test_framework_metadata"]["framework"])
        self.assertNotIn("patch_url", payload)
        self.assertEqual(payload["test_framework_metadata"]["test"]["branch"], "ganges-7.6.1-stable")
        joined = " ".join(payload["tester_tags"])
        self.assertNotIn("patch_url__", joined)
        self.assertIn("official", payload["tester_tags"])
        self.assertIn("infra__cdp", payload["tester_tags"])

    def test_same_mainline_7606_to_761_keeps_patch_data(self):
        test_patch = (
            "https://nugerrit.ntnxdpro.com/changes/"
            "nutest-py3-tests~ganges-7.6.0.6-stable~I333/patch?zip"
        )
        fw_patch = (
            "https://nugerrit.ntnxdpro.com/changes/"
            "nutest-py3~ganges-7.6-stable~I444/patch?zip"
        )
        source = {
            "test_framework_metadata": {
                "test": {"branch": "ganges-7.6.0.6-stable", "patch_url": test_patch},
                "framework": {"branch": "ganges-7.6-stable", "patch_url": fw_patch},
            },
            "patch_url": fw_patch,
            "tester_tags": ["official", "patch_url__" + test_patch, "framework_patch_url__" + fw_patch],
        }
        payload = {
            "test_framework_metadata": source["test_framework_metadata"],
            "patch_url": fw_patch,
            "tester_tags": list(source["tester_tags"]),
        }
        test_kept, fw_kept, warnings = resolve_clone_patches(source, "ganges-7.6.1-stable")
        self.assertEqual(warnings, [])
        self.assertEqual(test_kept, test_patch)
        self.assertEqual(fw_kept, fw_patch)
        apply_clone_patch_fields(payload, "ganges-7.6.1-stable", test_kept, fw_kept)
        clear_run_tests_with_tags(payload)
        restore_clone_patch_tags(payload, source, test_kept, fw_kept)
        self.assertEqual(payload["test_framework_metadata"]["test"]["patch_url"], test_patch)
        self.assertEqual(payload["test_framework_metadata"]["framework"]["patch_url"], fw_patch)
        self.assertEqual(payload["patch_url"], fw_patch)
        self.assertIn("patch_url__" + test_patch, payload["tester_tags"])
        self.assertIn("framework_patch_url__" + fw_patch, payload["tester_tags"])
        self.assertIn("official", payload["tester_tags"])

    def test_75_to_73_is_also_incompatible(self):
        source = {
            "test_framework_metadata": {
                "test": {
                    "branch": "ganges-7.5-stable",
                    "patch_url": "https://example.com/changes/nutest-py3-tests~ganges-7.5-stable~I9/patch?zip",
                },
                "framework": {},
            }
        }
        test_kept, fw_kept, warnings = resolve_clone_patches(source, "ganges-7.3-stable")
        self.assertIsNone(test_kept)
        self.assertIsNone(fw_kept)
        self.assertEqual(len(warnings), 1)
        self.assertIn("ganges-7.5-stable", warnings[0])

    def test_patch_without_a_known_branch_is_kept(self):
        source = {
            "test_framework_metadata": {
                "test": {"patch_url": "https://example.com/patches/tests.zip"},
                "framework": {},
            }
        }
        test_kept, fw_kept, warnings = resolve_clone_patches(source, "ganges-7.6.1-stable")
        self.assertEqual(test_kept, "https://example.com/patches/tests.zip")
        self.assertIsNone(fw_kept)
        self.assertEqual(warnings, [])

    def test_top_level_patch_url_is_the_framework_patch(self):
        source = {
            "patch_url": "https://example.com/changes/nutest-py3~ganges-7.6-stable~I1/patch?zip",
            "test_framework_metadata": {"framework": {"branch": "ganges-7.6-stable"}},
            "nutest-py3-tests_branch": "ganges-7.6-stable",
        }
        _test_kept, fw_kept, warnings = resolve_clone_patches(source, "ganges-7.6.1-stable")
        self.assertEqual(fw_kept, source["patch_url"])
        self.assertEqual(warnings, [])

    def test_caller_override_replaces_source_patch(self):
        source, _test_patch, _fw_patch = _official_jp_77()
        override = "https://example.com/changes/nutest-py3-tests~ganges-7.6-stable~Inew/patch?zip"
        test_kept, fw_kept, warnings = resolve_clone_patches(
            source,
            "ganges-7.6.1-stable",
            test_override=override,
            framework_override=override,
        )
        self.assertEqual(test_kept, override)
        self.assertEqual(fw_kept, override)
        self.assertEqual(warnings, [])

    def test_encoded_branch_wins_over_metadata_branch(self):
        url = (
            "https://nugerrit.ntnxdpro.com/changes/"
            "nutest-py3-tests~ganges-7.6-stable~Ikeep/patch?zip"
        )
        source = {
            "test_framework_metadata": {
                "test": {"branch": "ganges-7.7-stable", "patch_url": url},
                "framework": {},
            }
        }
        test_kept, _, warnings = resolve_clone_patches(source, "ganges-7.6.1-stable")
        self.assertEqual(test_kept, url)
        self.assertEqual(warnings, [])


class TestCloneTestSetsAndPatchesTogether(unittest.TestCase):
    def test_77_source_to_761_keeps_testsets_and_flags_patches(self):
        source, test_patch, fw_patch = _official_jp_77()
        plan = plan_source_test_set_links(source)
        test_kept, fw_kept, warnings = resolve_clone_patches(source, "ganges-7.6.1-stable")
        payload = {
            "name": "CDP_Regression_FullReg_7.6.1_Official",
            "test_sets": [{"$oid": oid} for oid in plan["ids"]],
            "tester_tags": list(source["tester_tags"]),
            "test_framework_metadata": source["test_framework_metadata"],
            "patch_url": source["patch_url"],
        }
        apply_clone_patch_fields(payload, "ganges-7.6.1-stable", test_kept, fw_kept)
        clear_run_tests_with_tags(payload)
        restore_clone_patch_tags(payload, source, test_kept, fw_kept)
        self.assertEqual(
            [row["$oid"] for row in payload["test_sets"]],
            ["a" * 24, "b" * 24, "c" * 24, "e" * 24],
        )
        self.assertIsNone(test_kept)
        self.assertIsNone(fw_kept)
        self.assertTrue(any(test_patch in w for w in warnings))
        self.assertTrue(any(fw_patch in w for w in warnings))
        self.assertNotIn("patch_url", payload)

    def test_compatible_official_jp_keeps_testsets_and_patches(self):
        test_patch = "https://nugerrit.ntnxdpro.com/changes/nutest-py3-tests~ganges-7.6-stable~Ia/patch?zip"
        fw_patch = "https://nugerrit.ntnxdpro.com/changes/nutest-py3~ganges-7.6-stable~Ib/patch?zip"
        source = {
            "test_sets": [{"$oid": "a" * 24}, {"$oid": "b" * 24}],
            "test_framework_metadata": {
                "test": {"branch": "ganges-7.6-stable", "patch_url": test_patch},
                "framework": {"branch": "ganges-7.6-stable", "patch_url": fw_patch},
            },
            "patch_url": fw_patch,
            "tester_tags": ["official", "patch_url__" + test_patch],
        }
        plan = plan_source_test_set_links(source)
        test_kept, fw_kept, warnings = resolve_clone_patches(source, "7.6.1")
        self.assertEqual(plan["ids"], ["a" * 24, "b" * 24])
        self.assertEqual(warnings, [])
        self.assertEqual(test_kept, test_patch)
        self.assertEqual(fw_kept, fw_patch)


class TestCloneDuplicateStop(unittest.TestCase):
    def test_existing_target_blocks_create(self):
        block = clone_target_block("abc123", None, "CDP_Regression_FullReg_7.6.1_Official")
        self.assertEqual(block["status"], 409)
        self.assertTrue(block["body"]["already_exists"])
        self.assertFalse(block["body"]["success"])
        self.assertIn("already exists", block["body"]["error"])
        self.assertIn("left unchanged", block["body"]["error"])
        self.assertEqual(block["body"]["job_profile"]["_id"], "abc123")
        self.assertNotIn("created", block["body"])

    def test_lookup_failure_blocks_create(self):
        block = clone_target_block(None, "JITA name lookup returned HTTP 500", "CDP_7.6.1")
        self.assertEqual(block["status"], 503)
        self.assertFalse(block["body"]["success"])
        self.assertNotIn("already_exists", block["body"])
        self.assertIn("No job profile was created", block["body"]["error"])

    def test_free_name_allows_create(self):
        self.assertIsNone(clone_target_block(None, None, "CDP_Regression_FullReg_7.6.1_Official"))
        self.assertIsNone(clone_target_block("", "", "name"))

    def test_create_route_stops_before_any_jita_post(self):
        path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("def dynamic_jp_create(")
        end = src.index("\ndef dynamic_jp_update(")
        body = src[start:end]
        abort_at = body.index("clone_target_block(")
        post_at = body.index("requests.post(")
        self.assertLess(abort_at, post_at)
        # The stop returns the block status; it does not fall through into create.
        window = body[abort_at:post_at]
        self.assertIn('return jsonify(body), block["status"]', window)


if __name__ == "__main__":
    unittest.main()
