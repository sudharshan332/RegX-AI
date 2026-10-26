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


ROOT_761 = "test_sets/milestones/7.6.1/CDP"
FEAT_761 = ROOT_761 + "/FEATS/FEAT-1/suite.lst"
REG_761 = ROOT_761 + "/REGRESSION/official.lst"


def _summary_row(name, paths, status="", component="Stargate", components=None, qi=None, tickets=None, triaged=False):
    published = {}
    if qi is not None:
        published = {"operation_success_percentage": qi}
    metadata = {"primary_component": component}
    if components is not None:
        metadata["components"] = components
    last_result = [{
        "pass_name": "overall",
        "run": {"status": status, "tickets": tickets or [], "is_triaged": triaged},
        "published": published,
    }]
    return {
        "name": name,
        "test_case": {
            "name": name,
            "test_sets": paths,
            "owners": [],
            "metadata": metadata,
        },
        "last_result": last_result,
    }


class ReleaseSummaryTests(unittest.TestCase):
    def test_all_scope_has_no_release_or_tag_exclusion(self):
        clauses = rd.summary_match("7.6.1", "all")["$and"]
        self.assertIn({"target_milestone": "7.6.1"}, clauses)
        self.assertIn({"additional_data.team": "7.6.1/CDP"}, clauses)
        self.assertIn({"deleted": False}, clauses)
        self.assertFalse(any("release_name" in clause for clause in clauses))
        self.assertFalse(any("test_case.metadata.tags" in clause for clause in clauses))

    def test_feat_keeps_this_release_and_drops_longevity_tags(self):
        clauses = rd.summary_match("7.6.1", "Feat")["$and"]
        self.assertIn({"release_name": "7.6.1"}, clauses)
        self.assertIn(
            {"test_case.metadata.tags": {"$nin": ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]}},
            clauses,
        )

    def test_regression_excludes_this_release(self):
        clauses = rd.summary_match("7.6.1", "regression")["$and"]
        self.assertIn({"release_name": {"$ne": "7.6.1"}}, clauses)
        self.assertIn(
            {"test_case.metadata.tags": {"$nin": ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]}},
            clauses,
        )

    def test_tcms_links_follow_the_milestone_page(self):
        overall = rd.tcms_page_url("7.6.1", "all")
        feat = rd.tcms_page_url("7.6.1", "feat")
        regression = rd.tcms_page_url("7.6.1", "regression")
        self.assertIn("type=All", overall)
        self.assertIn("tab=package_type", overall)
        self.assertIn("type=Feat", feat)
        self.assertNotIn("tab=package_type", feat)
        self.assertIn("type=Regression", regression)
        self.assertIn("7.6.1%2FCDP", overall)

    def test_summary_counts_handover_and_component_qi(self):
        rows = [
            _summary_row("cdp.a.Test.pending", [FEAT_761], component="Stargate", qi=50),
            _summary_row("cdp.a.Test.passed", [FEAT_761, REG_761], status="Succeeded", component="Stargate", qi=100),
            _summary_row("cdp.a.Test.failed", [REG_761], status="Failed", component="Curator", qi=0),
        ]
        summary = rd.build_summary(rows, "7.6.1", "all", root=ROOT_761, branch="ganges-7.6-stable")
        self.assertTrue(summary["show_regression"])
        self.assertTrue(summary["show_handover"])
        self.assertEqual(summary["execution"]["total"], 3)
        self.assertEqual(summary["execution"]["passed"], 1)
        self.assertEqual(summary["execution"]["failed"], 1)
        self.assertEqual(summary["execution"]["not_run"], 1)
        self.assertEqual(summary["handover"]["pending_feats"], 1)
        self.assertEqual(summary["handover"]["tests_not_handed_over"], 1)
        self.assertEqual(summary["handover"]["tests_not_run"], 1)
        stargate = next(row for row in summary["components"] if row["component"] == "Stargate")
        self.assertEqual(stargate["passed"], 1)
        self.assertEqual(stargate["total"], 2)
        self.assertEqual(stargate["qi"], 75.0)
        regression = rd.build_summary(rows, "7.6.1", "regression", root=ROOT_761, branch="ganges-7.6-stable")
        self.assertIsNone(regression["handover"])
        self.assertFalse(regression["show_handover"])
        feat = rd.build_summary(rows, "7.6.1", "feat", root=ROOT_761, branch="ganges-7.6-stable")
        self.assertFalse(feat["show_regression"])
        self.assertEqual(feat["handover"]["pending_feats"], 1)

    def test_metrics_qi_replaces_the_row_average(self):
        present = {
            "execution": {
                "qi": 94.73,
                "qi_source": "tcms_rows",
                "total": 10,
                "passed": 9,
                "failed": 1,
                "not_run": 0,
                "run_percentage": 100,
            },
        }
        rd.apply_metrics_qi(present, {
            "qi": 70,
            "total": 1833,
            "run": 1447,
            "passed": 1125,
            "failed": 322,
            "not_run": 386,
            "run_percentage": 79,
            "triage_percentage": 92,
            "total_triaged": 297,
        })
        execution = present["execution"]
        self.assertEqual(execution["qi"], 70)
        self.assertEqual(execution["qi_source"], "tcms_metrics")
        self.assertEqual(execution["total"], 1833)
        self.assertEqual(execution["passed"], 1125)
        self.assertEqual(execution["failed"], 322)
        self.assertEqual(execution["not_run"], 386)
        self.assertEqual(execution["run_percentage"], 79)
        self.assertEqual(execution["triage_percentage"], 92)
        self.assertEqual(execution["total_triaged"], 297)

    def test_component_table_lists_every_component_and_colors_qi(self):
        rows = [
            _summary_row(
                "cdp.a.both", [FEAT_761], status="Failed", component="Stargate",
                components=["Stargate", "Curator"], qi=84, tickets=["ENG-1"], triaged=True,
            ),
            _summary_row(
                "cdp.a.yellow", [FEAT_761], status="Failed", component="Curator",
                qi=87, tickets=["eng-2"], triaged=False,
            ),
            _summary_row("cdp.a.green", [REG_761], status="Succeeded", component="Stargate", qi=92),
            _summary_row("cdp.a.red", [REG_761], status="Failed", component="Cassandra", qi=84),
        ]
        summary = rd.build_summary(rows, "7.6.1", "regression", root=ROOT_761, branch="ganges-7.6-stable")
        by_name = {row["component"]: row for row in summary["components"]}
        stargate = by_name["Stargate"]
        self.assertEqual(stargate["total"], 2)
        self.assertEqual(stargate["passed"], 1)
        self.assertEqual(stargate["failed"], 1)
        self.assertEqual(stargate["run"], 2)
        self.assertEqual(stargate["not_run"], 0)
        self.assertEqual(stargate["qi"], 88.0)
        self.assertEqual(stargate["qi_tone"], "yellow")
        self.assertEqual(stargate["triaged_percentage"], 100.0)
        self.assertEqual(stargate["open_bugs"], ["ENG-1"])
        curator = by_name["Curator"]
        self.assertEqual(curator["total"], 2)
        self.assertEqual(curator["failed"], 2)
        self.assertEqual(curator["triaged_percentage"], 50.0)
        self.assertEqual(curator["open_bug_count"], 2)
        self.assertEqual(curator["open_bugs"], ["ENG-1", "ENG-2"])
        self.assertEqual(by_name["Cassandra"]["qi_tone"], "red")
        self.assertIn("tab=bugs", curator["bugs_url"])
        self.assertIn("Curator", curator["bugs_url"])
        self.assertIn("bug_types=product,test,framework,infra,other", curator["bugs_url"])
        self.assertIn("tab=test_case.metadata.components", summary["components_url"])
        self.assertEqual(rd.qi_tone(84.9), "red")
        self.assertEqual(rd.qi_tone(85), "yellow")
        self.assertEqual(rd.qi_tone(90), "green")
        self.assertEqual(rd.qi_tone(None), "")

    def test_component_metrics_keep_the_exact_tcms_qi(self):
        components = [
            {"component": "Curator", "qi": 85.0, "qi_tone": "yellow", "qi_source": "tcms_rows"},
            {"component": "Stargate", "qi": 80.0, "qi_tone": "red", "qi_source": "tcms_rows"},
            {"component": "Cassandra", "qi": 91.0, "qi_tone": "green", "qi_source": "tcms_rows"},
        ]
        rows = rd.apply_component_metrics(components, [
            {
                "_id": {"pass_name": "overall", "field_name": "Curator"},
                "average_total_op_success_percentage": 62,
                "total": 224,
                "run": 180,
                "not_run": 44,
                "passed": 100,
                "failed": 80,
                "triage_percentage": 90,
                "total_triaged": 72,
                "openBugs": 5,
                "unique_tickets": ["ENG-1", "ENG-2"],
            },
            {"name": "Stargate", "average_total_op_success_percentage": 89.5, "total": 1017},
            {"test_case.metadata.components": "Cassandra", "average_total_op_success_percentage": 90},
        ])
        by_name = {row["component"]: row for row in rows}
        self.assertEqual(by_name["Curator"]["qi"], 62.0)
        self.assertEqual(by_name["Curator"]["qi_tone"], "red")
        self.assertEqual(by_name["Curator"]["qi_source"], "tcms_metrics")
        self.assertEqual(by_name["Curator"]["total"], 224)
        self.assertEqual(by_name["Curator"]["run"], 180)
        self.assertEqual(by_name["Curator"]["not_run"], 44)
        self.assertEqual(by_name["Curator"]["passed"], 100)
        self.assertEqual(by_name["Curator"]["failed"], 80)
        self.assertEqual(by_name["Curator"]["triaged_percentage"], 90.0)
        self.assertEqual(by_name["Curator"]["total_triaged"], 72)
        self.assertEqual(by_name["Curator"]["open_bug_count"], 5)
        self.assertEqual(by_name["Curator"]["open_bugs"], ["ENG-1", "ENG-2"])
        self.assertEqual(by_name["Stargate"]["qi"], 89.5)
        self.assertEqual(by_name["Stargate"]["qi_tone"], "yellow")
        self.assertEqual(by_name["Stargate"]["total"], 1017)
        self.assertEqual(by_name["Cassandra"]["qi"], 90.0)
        self.assertEqual(by_name["Cassandra"]["qi_tone"], "green")
        self.assertEqual(by_name["Cassandra"]["qi_source"], "tcms_metrics")
        self.assertEqual(rows[0]["component"], "Stargate")
        untouched = [{"component": "Curator", "qi": 70.0, "qi_tone": "red"}]
        rd.apply_component_metrics(untouched, None)
        self.assertEqual(untouched[0]["qi"], 70.0)
        self.assertEqual(untouched[0]["qi_source"], "tcms_rows")
        match = rd.component_metrics_match("7.6.1", "regression")["$and"]
        self.assertIn({"additional_data.team": "7.6.1/CDP"}, match)
        self.assertIn({"release_name": {"$ne": "7.6.1"}}, match)

    def test_active_bugs_follow_the_latest_jita_ticket(self):
        records = [
            {"name": "same_case", "result": "fail", "qi": 80, "tickets": ["ENG-1"], "components": ["Curator"]},
            {"name": "diff_case", "result": "fail", "qi": 40, "tickets": ["ENG-2"], "components": ["Curator"]},
            {"name": "missing_case", "result": "fail", "qi": 10, "tickets": ["ENG-3"], "components": ["Curator"]},
        ]
        latest = rd.latest_jita_by_test([
            {"label": "Full regression", "tag": "full", "tests": [
                {"name": "same_case", "status": "Failed", "jira_tickets": ["ENG-1"], "task_time": 10, "agave_task_id": "old"},
                {"name": "diff_case", "status": "Failed", "jira_tickets": ["ENG-1"], "task_time": 10, "agave_task_id": "old-diff"},
            ]},
            {"label": "Upgrade", "tag": "upgrade", "tests": [
                {"name": "diff_case", "status": "Failed", "jira_tickets": ["ENG-9"], "task_time": 30, "agave_task_id": "new"},
            ]},
        ])
        self.assertEqual(latest["diff_case"]["tickets"], ["ENG-9"])
        self.assertEqual(latest["same_case"]["tickets"], ["ENG-1"])
        self.assertNotIn("missing_case", latest)
        curator = rd.active_bugs_by_component(records, latest)[0]
        active = {bug["ticket"]: bug for bug in curator["active_bugs"]}
        self.assertEqual(active["ENG-1"]["match"], "same")
        self.assertEqual(active["ENG-1"]["tests"], ["same_case"])
        self.assertEqual(active["ENG-9"]["match"], "different")
        self.assertEqual(active["ENG-9"]["tests"], ["diff_case"])
        self.assertNotIn("ENG-2", active)
        self.assertNotIn("ENG-3", active)
        self.assertEqual(
            [bug["ticket"] for bug in curator["top_qi"]],
            ["ENG-3", "ENG-9", "ENG-1"],
        )

    def test_comparison_classes_and_pass_on_any_tag(self):
        tcms = [
            {"name": "cdp.sync", "status": "", "result": "other", "tickets": []},
            {"name": "cdp.mismatch", "status": "Failed", "result": "fail", "tickets": []},
            {"name": "cdp.match", "status": "Succeeded", "result": "pass", "tickets": []},
            {"name": "cdp.missing", "status": "Succeeded", "result": "pass", "tickets": []},
        ]
        report = rd.build_comparison(tcms, [{
            "label": "Full regression",
            "tag": "full",
            "task_count": 3,
            "tests": [
                {"name": "cdp.sync", "status": "Succeeded"},
                {"name": "cdp.mismatch", "status": "Succeeded"},
                {"name": "cdp.match", "status": "Succeeded"},
                {"name": "cdp.outside", "status": "Failed"},
            ],
        }])
        self.assertEqual([item["name"] for item in report["sync_gap"]["items"]], ["cdp.sync"])
        self.assertEqual([item["name"] for item in report["status_mismatch"]["items"]], ["cdp.mismatch"])
        self.assertEqual([item["name"] for item in report["not_triggered"]["items"]], ["cdp.missing"])
        self.assertEqual([item["name"] for item in report["outside_tcms"]["items"]], ["cdp.outside"])
        self.assertEqual(report["matched_count"], 1)
        self.assertEqual(report["per_tag"][0]["task_count"], 3)

        union = rd.build_comparison(
            [{"name": "cdp.a", "status": "Succeeded", "result": "pass", "tickets": []}],
            [
                {"label": "Full regression", "tag": "full", "task_count": 1, "tests": [{"name": "cdp.a", "status": "Failed"}]},
                {"label": "Upgrade", "tag": "upgrade", "task_count": 1, "tests": [{"name": "cdp.a", "status": "Succeeded"}]},
            ],
        )
        self.assertEqual(union["combined"]["passed"], 1)
        self.assertEqual(union["status_mismatch"]["count"], 0)
        self.assertEqual(union["matched_count"], 1)
        self.assertEqual(union["per_tag"][0]["failed"], 1)
        self.assertEqual(union["per_tag"][1]["passed"], 1)

    def test_bulk_tickets_need_more_than_five_failed_tests(self):
        records = [
            {"name": "t%s" % index, "result": "fail", "tickets": ["ENG-1"]}
            for index in range(6)
        ]
        self.assertEqual(len(rd.bulk_tickets(records)["ENG-1"]), 6)
        self.assertEqual(rd.bulk_tickets(records[:5]), {})
        records.append({"name": "passed", "result": "pass", "tickets": ["ENG-2"]})
        self.assertNotIn("ENG-2", rd.bulk_tickets(records))

    def test_jita_tags_are_saved_per_milestone(self):
        import tempfile
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "release_dashboard_jita_tags.json")
        saved = rd.save_jita_tags("7.6.1", [
            {"label": "Full regression", "tag": "full-reg"},
            {"label": "Full regression", "tag": "full-reg"},
            {"label": "Upgrade", "tag": "upgrade-tag"},
        ], path=path)
        self.assertEqual(saved, [
            {"label": "Full regression", "tag": "full-reg"},
            {"label": "Upgrade", "tag": "upgrade-tag"},
        ])
        self.assertEqual(rd.load_jita_tags("7.6.1", path=path), saved)
        self.assertEqual(rd.load_jita_tags("7.7", path=path), [])
        with self.assertRaises(rd.DashboardError):
            rd.normalize_tags([{"label": "Full regression", "tag": "bad\ntag"}])


if __name__ == "__main__":
    unittest.main()
