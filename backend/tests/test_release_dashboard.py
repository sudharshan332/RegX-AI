"""Color rules for the read-only release dashboard."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import release_dashboard as rd  # noqa: E402


def _row(name, paths, status="", issue_type="", tickets=None):
    last_result = []
    if status or issue_type or tickets:
        last_result = [{
            "pass_name": "overall",
            "run": {
                "status": status,
                "issue_type": issue_type,
                "tickets": tickets or [],
            },
        }]
    return {
        "name": name,
        "test_case": {
            "name": name,
            "test_sets": paths,
            "owners": ["owner@nutanix.com"],
        },
        "last_result": last_result,
    }


FEAT = "test_sets/milestones/7.7/CDP/FunctionalTest/FEATS/Kronos-FEAT-1/suite.lst"
REG = "test_sets/milestones/7.7/CDP/FunctionalTest/REGRESSION/official.lst"
TRANSIT = "test_sets/intransit/CDP/FunctionalTest/FEATS/Kronos-FEAT-1/suite.lst"
OTHER_RELEASE = "test_sets/milestones/7.6/CDP/REGRESSION/official.lst"


class ReleaseDashboardColorTests(unittest.TestCase):
    def test_black_when_nothing_is_in_regression(self):
        data = rd.build_dashboard([
            _row("cdp.a.Test.t1", [FEAT]),
            _row("cdp.a.Test.t2", [FEAT, TRANSIT, OTHER_RELEASE]),
        ], "7.7")
        feat = data["feats"][0]
        self.assertEqual(feat["name"], "Kronos-FEAT-1")
        self.assertEqual(feat["color"], "black")
        self.assertEqual(feat["handed_over"], 0)
        self.assertEqual(feat["total"], 2)

    def test_black_when_handover_is_partial(self):
        data = rd.build_dashboard([
            _row("cdp.a.Test.t1", [FEAT, REG], status="Succeeded"),
            _row("cdp.a.Test.t2", [FEAT]),
        ], "7.7")
        feat = data["feats"][0]
        self.assertEqual(feat["color"], "black")
        self.assertEqual(feat["handed_over"], 1)
        self.assertEqual(feat["total"], 2)

    def test_same_test_name_in_a_separate_regression_row_counts(self):
        data = rd.build_dashboard([
            _row("cdp.a.Test.t1", [FEAT]),
            _row("cdp.a.Test.t1", [REG], status="Succeeded"),
        ], "7.7")
        feat = data["feats"][0]
        self.assertEqual(feat["color"], "green")
        self.assertEqual(feat["total"], 1)
        self.assertEqual(feat["tests"][0]["status"], "Succeeded")

    def test_green_when_every_matched_test_passed(self):
        data = rd.build_dashboard([
            _row("cdp.a.Test.t1", [FEAT, REG], status="Succeeded"),
            _row("cdp.a.Test.t2", [FEAT, REG], status="Passed"),
        ], "7.7")
        self.assertEqual(data["feats"][0]["color"], "green")
        self.assertEqual(data["feats"][0]["pass_rate"], 100)

    def test_yellow_when_pass_rate_is_above_80(self):
        rows = [
            _row("cdp.a.Test.t%s" % i, [FEAT, REG], status="Succeeded")
            for i in range(9)
        ]
        rows.append(_row(
            "cdp.a.Test.fail",
            [FEAT, REG],
            status="Failed",
            issue_type="Product",
            tickets=["ENG-1"],
        ))
        feat = rd.build_dashboard(rows, "7.7")["feats"][0]
        self.assertEqual(feat["color"], "yellow")
        self.assertEqual(feat["pass_rate"], 90)
        failed = feat["tests"][0]
        self.assertEqual(failed["name"], "cdp.a.Test.fail")
        self.assertEqual(failed["issue_type"], "Product")
        self.assertEqual(failed["tickets"], ["ENG-1"])

    def test_red_when_pass_rate_is_80_or_below(self):
        rows = [
            _row("cdp.a.Test.p%s" % i, [FEAT, REG], status="Succeeded")
            for i in range(8)
        ]
        rows.extend(
            _row("cdp.a.Test.f%s" % i, [FEAT, REG], status="Failed")
            for i in range(2)
        )
        feat = rd.build_dashboard(rows, "7.7")["feats"][0]
        self.assertEqual(feat["color"], "red")
        self.assertEqual(feat["pass_rate"], 80)

    def test_regression_folder_is_not_listed_as_a_feat(self):
        data = rd.build_dashboard([
            _row("cdp.a.Test.t1", [FEAT]),
            _row("cdp.a.Test.t2", [REG], status="Failed"),
        ], "7.7")
        self.assertEqual([feat["name"] for feat in data["feats"]], ["Kronos-FEAT-1"])
        self.assertEqual(data["root"], "test_sets/milestones/7.7/CDP/FunctionalTest")
        self.assertIn("ganges-7.7-stable", data["sourcegraph"])

    def test_nested_feat_folders_are_separate_rows(self):
        data = rd.build_dashboard([
            _row("cdp.a.Test.a", [
                "test_sets/milestones/7.7/CDP/FunctionalTest/FEATS/FEAT-19686/FEAT-17396/a.lst",
            ]),
            _row("cdp.a.Test.b", [
                "test_sets/milestones/7.7/CDP/FunctionalTest/FEATS/FEAT-19686/FEAT-18094/b.lst",
            ]),
            _row("cdp.a.Test.c", [
                "test_sets/milestones/7.7/CDP/FunctionalTest/FEATS/FEAT-19506/c.lst",
            ]),
            _row("cdp.a.Test.reg", [REG], status="Failed"),
        ], "7.7")
        self.assertEqual(
            [feat["name"] for feat in data["feats"]],
            ["FEAT-19506", "FEAT-19686/FEAT-17396", "FEAT-19686/FEAT-18094"],
        )

    def test_7_6_groups_each_feat_under_feats(self):
        data = rd.build_dashboard([
            _row("cdp.a.Test.t1", [
                "test_sets/milestones/7.6/CDP/FEATS/Janus-FEAT-1/suite.lst",
                "test_sets/milestones/7.6/CDP/REGRESSION/official.lst",
            ], status="Succeeded"),
        ], "7.6")
        self.assertEqual(data["feats"][0]["name"], "Janus-FEAT-1")
        self.assertEqual(data["feats"][0]["color"], "green")
        self.assertEqual(data["root"], "test_sets/milestones/7.6/CDP")
        self.assertIn("ganges-7.6-stable", data["sourcegraph"])

    def test_overall_success_is_ignored_when_this_branch_did_not_run(self):
        row = _row("cdp.a.Test.t1", [FEAT, REG])
        row["last_result"] = [
            {"pass_name": "overall", "run": {"status": "Succeeded"}},
            {"pass_name": "RC1", "run": {"status": ""}},
            {"pass_name": "RC2", "run": {"status": ""}},
            {"pass_name": "RC3", "run": {"status": ""}},
        ]
        data = rd.build_dashboard([row], "7.7")
        feat = data["feats"][0]
        self.assertEqual(feat["tests"][0]["status"], "Not run")
        self.assertEqual(feat["color"], "not_run")

    def test_latest_branch_pass_wins_over_overall(self):
        row = _row("cdp.a.Test.t1", [FEAT, REG])
        row["last_result"] = [
            {"pass_name": "overall", "run": {"status": "Succeeded"}},
            {"pass_name": "RC1", "run": {"status": "Succeeded"}},
            {"pass_name": "RC3", "run": {"status": "Failed"}},
        ]
        data = rd.build_dashboard([row], "7.7")
        self.assertEqual(data["feats"][0]["tests"][0]["status"], "Failed")
        self.assertEqual(data["feats"][0]["color"], "red")

    def test_newer_branch_pass_wins_even_when_its_number_is_lower(self):
        row = _row("cdp.a.Test.t1", [FEAT, REG])
        row["last_result"] = [
            {"pass_name": "overall", "run": {"status": "Succeeded", "end_time": {"$date": 300}}},
            {"pass_name": "RC3", "run": {"status": "Succeeded", "end_time": {"$date": 100}}},
            {"pass_name": "RC1", "run": {"status": "Failed", "end_time": {"$date": 200}}},
        ]
        data = rd.build_dashboard([row], "7.7")
        self.assertEqual(data["feats"][0]["tests"][0]["status"], "Failed")

    def test_result_from_another_product_branch_is_not_run(self):
        row = _row("cdp.a.Test.t1", [FEAT, REG], status="Succeeded")
        row["target_branch"] = "ncc-6.1.0-release"
        data = rd.build_dashboard([row], "7.7")
        self.assertEqual(data["feats"][0]["tests"][0]["status"], "Not run")

    def test_pc_branch_matches_the_release_and_ncc_does_not(self):
        self.assertTrue(rd._branch_matches_release(
            "ganges-7.6-stable-pc", "ganges-7.6-stable", "7.6",
        ))
        self.assertTrue(rd._branch_matches_release(
            "ganges-7.6.1-stable", "ganges-7.6-stable", "7.6.1",
        ))
        self.assertFalse(rd._branch_matches_release(
            "ganges-7.6.1-stable", "ganges-7.6-stable", "7.6",
        ))
        self.assertFalse(rd._branch_matches_release(
            "ncc-6.0.0-release", "ganges-7.6-stable", "7.6",
        ))

    def test_not_run_when_handover_is_complete_but_a_test_has_no_result(self):
        data = rd.build_dashboard([
            _row("cdp.a.Test.t1", [FEAT, REG], status="Succeeded"),
            _row("cdp.a.Test.t2", [FEAT, REG]),
        ], "7.7")
        self.assertEqual(data["feats"][0]["color"], "not_run")
        self.assertIsNone(data["feats"][0]["pass_rate"])


class ReleaseBranchTests(unittest.TestCase):
    def test_patch_versions_use_the_train_branch(self):
        self.assertEqual(rd.nutest_branch_for("7.6.1"), {
            "milestone": "7.6.1",
            "branch": "ganges-7.6-stable",
        })
        self.assertEqual(rd.nutest_branch_for("7.5.1"), {
            "milestone": "7.5.1",
            "branch": "ganges-7.5-stable",
        })
        self.assertEqual(rd.nutest_branch_for("master")["branch"], "master")
        self.assertEqual(rd.nutest_branch_for("ganges-7.6-stable")["milestone"], "7.6")

    def test_added_version_uses_its_milestone_folder_and_train_branch(self):
        info = rd.lookup_release("7.6.1")
        self.assertEqual(info["root"], "test_sets/milestones/7.6.1/CDP")
        self.assertEqual(info["branch"], "ganges-7.6-stable")

    def test_custom_root_groups_a_release_that_is_not_built_in(self):
        root = "test_sets/milestones/7.6.1/CDP"
        data = rd.build_dashboard([
            _row("cdp.a.Test.t1", [
                root + "/FEATS/FEAT-18439/suite.lst",
                root + "/REGRESSION/official.lst",
            ], status="Succeeded"),
        ], "7.6.1", root=root, branch="ganges-7.6-stable")
        self.assertEqual(data["feats"][0]["name"], "FEAT-18439")
        self.assertEqual(data["feats"][0]["color"], "green")
        self.assertEqual(data["branch"], "ganges-7.6-stable")
        self.assertEqual(data["root"], root)

    def test_known_releases_skip_the_search(self):
        info = rd.lookup_release("7.6")
        self.assertEqual(info["branch"], "ganges-7.6-stable")
        self.assertEqual(info["root"], "test_sets/milestones/7.6/CDP")


if __name__ == "__main__":
    unittest.main()
