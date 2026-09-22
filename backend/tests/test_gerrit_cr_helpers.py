"""Unit tests for Flux-style Gerrit CR helpers used by handover/deprecate."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestGerritCrHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("FLASK_ENV", "testing")
        try:
            import test_flask as tf
            cls.tf = tf
        except Exception as exc:
            raise unittest.SkipTest("test_flask import failed: %s" % exc) from exc

    def test_ensure_change_id_idempotent(self):
        msg = self.tf._ensure_change_id_in_message("Handover\n\nbody")
        self.assertIn("Change-Id: I", msg)
        again = self.tf._ensure_change_id_in_message(msg)
        self.assertEqual(msg.count("Change-Id:"), 1)
        self.assertEqual(again.count("Change-Id:"), 1)

    def test_parse_gerrit_push_url(self):
        out = (
            "remote: Processing changes: new: 1, refs: 1, done\n"
            "remote: New Changes:\n"
            "remote:   https://nugerrit.ntnxdpro.com/c/nutest-py3-tests/+/412345 Testcase Handover\n"
        )
        parsed = self.tf._parse_gerrit_push_result(
            out, "https://nugerrit.ntnxdpro.com", "nutest-py3-tests"
        )
        self.assertEqual(parsed["gerrit_change_id"], "412345")
        self.assertIn("/+/412345", parsed["gerrit_url"])

    def test_install_fallback_hook(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(os.path.join(repo, ".git", "hooks"))
            path = self.tf._install_gerrit_commit_msg_hook(repo, "https://invalid.example")
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(os.access(path, os.X_OK))


class TestHandoverNutestBranch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("FLASK_ENV", "testing")
        try:
            import test_flask as tf
            cls.tf = tf
        except Exception as exc:
            raise unittest.SkipTest("test_flask import failed: %s" % exc) from exc

    def test_patch_line_maps_to_release_mainline(self):
        self.assertEqual(self.tf._handover_nutest_branch("7.5.2"), "ganges-7.5-stable")
        self.assertEqual(self.tf._handover_nutest_branch("ganges-7.5.2-stable"), "ganges-7.5-stable")
        self.assertEqual(self.tf._handover_nutest_branch("ganges-7.5.1-stable"), "ganges-7.5-stable")
        self.assertEqual(self.tf._handover_nutest_branch("master"), "master")
        self.assertEqual(self.tf._handover_nutest_branch("ganges-7.5-stable"), "ganges-7.5-stable")

    def test_alias_candidates_prefer_mainline_before_patch(self):
        aliases = self.tf._branch_alias_candidates("7.5.2")
        self.assertEqual(aliases[0], "ganges-7.5-stable")
        patch_indexes = [i for i, name in enumerate(aliases) if "7.5.2" in name]
        self.assertTrue(patch_indexes)
        self.assertLess(aliases.index("ganges-7.5-stable"), patch_indexes[0])

        aliases_full = self.tf._branch_alias_candidates("ganges-7.5.2-stable")
        self.assertEqual(aliases_full[0], "ganges-7.5-stable")
        self.assertLess(
            aliases_full.index("ganges-7.5-stable"),
            aliases_full.index("ganges-7.5.2-stable"),
        )


class TestLstCrRemoveNotPresent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("FLASK_ENV", "testing")
        try:
            import test_flask as tf
            cls.tf = tf
        except Exception as exc:
            raise unittest.SkipTest("test_flask import failed: %s" % exc) from exc

    def test_partial_query_removed_is_not_listed_as_missing(self):
        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def get_file(self, branch, lf):
                return "testcases: [\ncdp.foo.MyTest.test_basic\n]\n"

            def publish_lst_edits(self, *a, **k):
                return {"success": True, "gerrit_change_id": "1", "gerrit_url": "http://x"}

        from unittest.mock import patch

        with patch("gerrit_lst_cr.GerritLstClient", FakeClient):
            result = self.tf._lst_cr_via_gerrit_rest(
                "master",
                ["foo.lst"],
                ["test_basic", "missing.test"],
                ["rev"],
                "msg",
                "user",
                "pw",
                "https://gerrit.example",
                "repo",
                mode="remove",
            )
        self.assertEqual(result["removed"], ["cdp.foo.MyTest.test_basic"])
        self.assertEqual(result["not_present"], ["missing.test"])
        self.assertNotIn("test_basic", result["not_present"])


if __name__ == "__main__":
    unittest.main()
