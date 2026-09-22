"""Unit tests for Intelligent Triage Phase 2 (schema, decision, persistence)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intelligent_triage.decision_engine import (  # noqa: E402
    DecisionOutcome,
    decide_outcome,
    should_auto_write_triage,
)
from intelligent_triage.intermittent import match_approved_intermittent  # noqa: E402
from intelligent_triage.orchestration import (  # noqa: E402
    build_intelligent_triage_payload,
    estimate_triage_confidence,
)
from intelligent_triage.schema import (  # noqa: E402
    build_analysis_from_first_level,
    build_empty_analysis,
    merge_glean_ai_validation,
)
from intelligent_triage import persistence as pers  # noqa: E402
from intelligent_triage.thresholds import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    load_team_thresholds,
    save_team_thresholds,
)


class TestSchemaConfidences(unittest.TestCase):
    def test_no_overall_confidence_field(self):
        analysis = build_empty_analysis("tc1", "test.foo", "Failed")
        self.assertNotIn("overall_confidence", analysis)
        self.assertIn("intermittent_confidence", analysis["intermittent_analysis"])
        self.assertIn("triage_confidence", analysis["triage_analysis"])

    def test_independent_confidences_preserved(self):
        first_level = {
            "issue_type": "Product Issue",
            "analysis": "Something failed",
            "recommended_action": "link",
            "best_matching_ticket": "ENG-1",
            "tg_ticket_validation": {
                "ticket": "ENG-1",
                "verdict": "Correct",
                "reason": "match",
                "is_open": True,
                "overlap_score": 5,
                "found_in_glean": True,
            },
            "enriched_tickets": [
                {"ticket": "ENG-1", "jira_status": "Open", "is_open": True, "jira_summary": "boom"},
            ],
            "glean_available": True,
            "glean_ok": True,
            "search_source": "glean",
            "search_queries": ["q"],
            "glean_snippets": [],
            "test_log_url": "http://log",
            "failure_stage": "Test Body",
        }
        intermittent = {
            "is_intermittent": True,
            "pattern_id": "timeout_cluster_start",
            "intermittent_confidence": 0.95,
            "approved_pattern": True,
            "ai_log_validation": None,
            "action": "rerun",
        }
        analysis = build_analysis_from_first_level(
            {"testcase_id": "1", "testcase_name": "t", "status": "Failed", "exception_summary": "x"},
            first_level,
            intermittent=intermittent,
            triage_confidence=0.88,
        )
        self.assertEqual(analysis["intermittent_analysis"]["intermittent_confidence"], 0.95)
        self.assertEqual(analysis["triage_analysis"]["triage_confidence"], 0.88)
        self.assertNotIn("overall_confidence", analysis)
        # Averaging must not happen
        avg = (0.95 + 0.88) / 2
        self.assertNotEqual(analysis["triage_analysis"]["triage_confidence"], avg)


class TestDecisionEngine(unittest.TestCase):
    def _base(self):
        a = build_empty_analysis("1", "t", "Failed")
        a["jita"]["exception_summary"] = "AssertionError: boom"
        a["jita"]["test_log_url"] = "http://logs/x"
        a["glean_candidates"]["search"]["mcp_health"] = {
            "service": "glean", "available": True, "ok": True, "error": None, "claimed_success": True
        }
        a["mcp_health"]["glean"] = a["glean_candidates"]["search"]["mcp_health"]
        return a

    def test_auto_triage(self):
        a = self._base()
        a["triage_genie"]["original"]["ticket"] = "ENG-1"
        a["triage_genie"]["ai_validation"] = {"verdict": "Correct", "is_open": True, "ticket": "ENG-1"}
        a["triage_analysis"]["triage_confidence"] = 0.9
        a["triage_analysis"]["best_matching_ticket"] = "ENG-1"
        a["glean_candidates"]["search"]["candidates"] = [
            {"ticket": "ENG-1", "match_score": 0.9, "is_open": True}
        ]
        d = decide_outcome(a)
        self.assertEqual(d["outcome"], DecisionOutcome.AUTO_TRIAGE.value)
        self.assertFalse(d["deep_ai_started"])

    def test_rerun_intermittent(self):
        a = self._base()
        a["intermittent_analysis"] = {
            "is_intermittent": True,
            "approved_pattern": True,
            "intermittent_confidence": 0.95,
            "ai_log_validation": None,
        }
        d = decide_outcome(a)
        self.assertEqual(d["outcome"], DecisionOutcome.RERUN_TESTCASE.value)

    def test_insufficient_evidence(self):
        a = build_empty_analysis("1", "t", "Failed")
        a["glean_candidates"]["search"]["mcp_health"] = {
            "available": False, "ok": False, "error": "auth", "claimed_success": False
        }
        d = decide_outcome(a)
        self.assertEqual(d["outcome"], DecisionOutcome.INSUFFICIENT_EVIDENCE.value)

    def test_needs_deep_analysis_not_started(self):
        a = self._base()
        a["triage_analysis"]["issue_type"] = "Product Issue"
        a["triage_analysis"]["triage_confidence"] = 0.4
        a["triage_genie"]["ai_validation"] = {"verdict": "Missing"}
        d = decide_outcome(a)
        self.assertEqual(d["outcome"], DecisionOutcome.NEEDS_DEEP_ANALYSIS.value)
        self.assertTrue(d["deep_ai_recommended"])
        self.assertFalse(d["deep_ai_started"])

    def test_hybrid_auto_write_requires_open_correct(self):
        a = self._base()
        a["triage_genie"]["ai_validation"] = {"verdict": "Correct", "is_open": True}
        d = {"outcome": "AUTO_TRIAGE"}
        self.assertTrue(should_auto_write_triage(d, a))
        a["triage_genie"]["ai_validation"] = {"verdict": "Correct", "is_open": False}
        self.assertFalse(should_auto_write_triage(d, a))
        a["triage_genie"]["ai_validation"] = {"verdict": "Partial", "is_open": True}
        self.assertFalse(should_auto_write_triage(d, a))


class TestIntermittentPatterns(unittest.TestCase):
    def test_approved_pattern_match(self):
        m = match_approved_intermittent(
            "Timedout executing command source /etc/profile; cluster start in 600 secs with error:"
        )
        self.assertTrue(m["is_intermittent"])
        self.assertTrue(m["approved_pattern"])
        self.assertGreaterEqual(m["intermittent_confidence"], 0.8)


class TestGleanAiValidationPersist(unittest.TestCase):
    def test_merge_keeps_search_separate(self):
        a = build_empty_analysis("1", "t", "Failed")
        a["glean_candidates"]["search"]["candidates"] = [
            {"ticket": "ENG-9", "match_score": 0.7, "is_open": True}
        ]
        merged = merge_glean_ai_validation(
            a, {"verdict": "Correct", "reason": "yes"}, ticket="ENG-9"
        )
        self.assertEqual(merged["glean_candidates"]["ai_validation"]["verdict"], "Correct")
        self.assertEqual(merged["glean_candidates"]["search"]["candidates"][0]["ai_validation"]["verdict"], "Correct")
        self.assertIsNotNone(merged["glean_candidates"]["search"]["candidates"])


class TestPersistenceMergeAndCanonicalPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_data = pers._DATA_ROOT
        pers._DATA_ROOT = self.tmp

    def tearDown(self):
        pers._DATA_ROOT = self._orig_data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tags_merge_legacy_and_canonical_team_file(self):
        legacy = os.path.join(self.tmp, "failed_analysis_saved_tags.json")
        with open(legacy, "w") as f:
            json.dump({"tags": [{"name": "legacy-tag", "added_at": "2026-01-01T00:00:00Z"}]}, f)
        loaded = pers.load_failed_analysis_tags(team="CDP_FT")
        names = [t["name"] for t in loaded["tags"]]
        self.assertIn("legacy-tag", names)

        pers.save_failed_analysis_tags(
            {"tags": [{"name": "team-tag", "added_at": "2026-02-01T00:00:00Z"}]},
            team="CDP_FT",
        )
        canonical = os.path.join(self.tmp, "CDP_FT", "failed_analysis_saved_tags.json")
        self.assertTrue(os.path.exists(canonical))
        merged = pers.load_failed_analysis_tags(team="CDP_FT")
        merged_names = [t["name"] for t in merged["tags"]]
        self.assertIn("team-tag", merged_names)
        self.assertIn("legacy-tag", merged_names)

    def test_empty_team_results_do_not_hide_legacy_rows(self):
        legacy = os.path.join(self.tmp, "failed_analysis_mytag.json")
        with open(legacy, "w") as f:
            json.dump({
                "tag": "mytag",
                "results": [{"testcase_id": "abc", "testcase_name": "t1"}],
                "intelligent_triage": {
                    "abc": {"decision": {"outcome": "AUTO_TRIAGE"}, "triage_analysis": {"summary": "x"}}
                },
            }, f)
        # Empty team write that previously shadowed legacy:
        team_dir = os.path.join(self.tmp, "CDP_FT", "failed_analysis")
        os.makedirs(team_dir, exist_ok=True)
        with open(os.path.join(team_dir, "results_mytag.json"), "w") as f:
            json.dump({"tag": "mytag", "results": [], "count": 0}, f)

        loaded = pers.load_failed_analysis_results("mytag", team="CDP_FT")
        self.assertEqual(len(loaded.get("results") or []), 1)
        self.assertIn("abc", loaded.get("intelligent_triage") or {})

    def test_save_merges_intelligent_triage(self):
        pers.save_failed_analysis_results(
            "keep",
            {
                "tag": "keep",
                "results": [{"testcase_id": "1"}],
                "intelligent_triage": {"1": {"decision": {"outcome": "NEEDS_DEEP_ANALYSIS"}}},
            },
            team="CDP_FT",
        )
        pers.save_failed_analysis_results(
            "keep",
            {"tag": "keep", "results": [{"testcase_id": "1"}, {"testcase_id": "2"}]},
            team="CDP_FT",
        )
        loaded = pers.load_failed_analysis_results("keep", team="CDP_FT")
        self.assertEqual(len(loaded["results"]), 2)
        self.assertIn("1", loaded["intelligent_triage"])


class TestPersistenceTeamScoped(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_data = pers._DATA_ROOT
        pers._DATA_ROOT = self.tmp

    def tearDown(self):
        pers._DATA_ROOT = self._orig_data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_team_read_legacy_fallback(self):
        # Seed legacy flat file
        legacy = os.path.join(self.tmp, "failed_analysis_mytag.json")
        with open(legacy, "w") as f:
            json.dump({"tag": "mytag", "results": [{"id": 1}]}, f)
        loaded = pers.load_failed_analysis_results("mytag", team="CDP_FT")
        self.assertEqual(loaded["results"][0]["id"], 1)

        pers.save_failed_analysis_results("mytag", {"tag": "mytag", "results": [{"id": 2}]}, team="CDP_FT")
        team_path = os.path.join(self.tmp, "CDP_FT", "failed_analysis", "results_mytag.json")
        self.assertTrue(os.path.exists(team_path))
        loaded2 = pers.load_failed_analysis_results("mytag", team="CDP_FT")
        self.assertEqual(loaded2["results"][0]["id"], 2)

    def test_delete_removes_team_and_legacy(self):
        pers.save_failed_analysis_results("gone", {"tag": "gone", "results": []}, team="CDP_FT")
        legacy = os.path.join(self.tmp, "failed_analysis_gone.json")
        with open(legacy, "w") as f:
            json.dump({"tag": "gone"}, f)
        pers.delete_failed_analysis_results("gone", team="CDP_FT")
        self.assertFalse(os.path.exists(legacy))
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp, "CDP_FT", "failed_analysis", "results_gone.json"))
        )


class TestThresholds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import intelligent_triage.thresholds as thr
        self.mod = thr
        self._orig = thr._DATA_ROOT
        thr._DATA_ROOT = self.tmp

    def tearDown(self):
        self.mod._DATA_ROOT = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_and_team_override(self):
        loaded = load_team_thresholds("CDP_FT")
        self.assertEqual(loaded["T_auto"], DEFAULT_THRESHOLDS["T_auto"])
        saved = save_team_thresholds({"T_auto": 0.9}, team="CDP_FT")
        self.assertEqual(saved["T_auto"], 0.9)
        self.assertEqual(load_team_thresholds("CDP_FT")["T_auto"], 0.9)


class TestOrchestrationPayload(unittest.TestCase):
    def test_build_payload_has_decision_and_split_confidence(self):
        first_level = {
            "issue_type": "Product Issue",
            "analysis": "x",
            "recommended_action": "review",
            "best_matching_ticket": "",
            "tg_ticket_validation": {"ticket": "", "verdict": "Missing", "reason": "none"},
            "enriched_tickets": [],
            "glean_available": True,
            "glean_ok": True,
            "search_source": "glean",
            "search_queries": [],
            "glean_snippets": [],
            "test_log_url": "http://x",
            "failure_stage": "Test Body",
        }
        payload = build_intelligent_triage_payload(
            {"testcase_id": "1", "testcase_name": "t", "status": "Failed", "exception_summary": "err"},
            first_level,
            thresholds=DEFAULT_THRESHOLDS,
        )
        self.assertIn("intelligent_triage", payload)
        self.assertIn("decision", payload)
        self.assertIsNotNone(payload["triage_confidence"])
        it = payload["intelligent_triage"]
        self.assertNotIn("overall_confidence", it)
        self.assertFalse(it["decision"]["deep_ai_started"])


if __name__ == "__main__":
    unittest.main()
