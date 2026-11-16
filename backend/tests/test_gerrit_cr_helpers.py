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

    def test_validation_revisions_prefer_cr_branch_and_skip_master(self):
        revs = self.tf._validation_revision_candidates("ganges-7.6-stable-pc")
        self.assertEqual(revs[0], "ganges-7.6-stable")
        self.assertIn("ganges-7.6-stable-pc", revs)
        self.assertNotIn("master", [r.lower() for r in revs])
        versioned = self.tf._validation_revision_candidates("7.5.2")
        self.assertEqual(versioned[0], "ganges-7.5-stable")
        self.assertNotIn("master", [r.lower() for r in versioned])

    def test_interpret_revision_blob(self):
        self.assertEqual(self.tf._interpret_revision_blob(True, "summary: x\n"), (True, True))
        self.assertEqual(self.tf._interpret_revision_blob(True, ""), (True, True))
        self.assertEqual(self.tf._interpret_revision_blob(True, None), (True, False))
        self.assertEqual(self.tf._interpret_revision_blob(False, None), (False, False))

    def test_lst_owner_prefers_test_owner(self):
        self.assertEqual(
            self.tf._lst_owner_from_payload({"test_owner": "qa.owner"}, "gerrit.user"),
            "qa.owner",
        )
        self.assertEqual(self.tf._lst_owner_from_payload({}, "gerrit.user"), "gerrit.user")
        self.assertEqual(self.tf._lst_owner_from_payload({"owner": "other.owner"}, "gerrit.user"), "other.owner")

    def test_validate_stops_on_first_existing_revision(self):
        calls = []

        def fake(repo, rev, path, explicit_token=None):
            calls.append(rev)
            if rev == "ganges-7.6-stable-pc":
                return "missing_rev", None, None
            if rev == "ganges-7.6-stable":
                return "missing_file", None, None
            return "ok", "should-not-use", None

        from unittest.mock import patch
        with patch.object(self.tf, "_query_revision_blob", fake):
            result = self.tf.validate_with_sourcegraph(
                "nugerrit.ntnxdpro.com/nutest-py3-tests",
                "ganges-7.6-stable-pc",
                "test_sets/foo.lst",
            )
        self.assertEqual(result["resolved_branch"], "ganges-7.6-stable")
        self.assertTrue(result["branch_valid"])
        self.assertFalse(result["file_valid"])
        self.assertNotIn("master", calls)

    def test_validate_exact_branch_file_including_empty(self):
        def fake(repo, rev, path, explicit_token=None):
            if rev == "my-feature" and path == "test_sets/a.lst":
                return "ok", "", None
            return "ok", "wrong-branch", None

        from unittest.mock import patch
        with patch.object(self.tf, "_query_revision_blob", fake):
            result = self.tf.validate_with_sourcegraph("repo", "my-feature", "test_sets/a.lst")
        self.assertEqual(result["resolved_branch"], "my-feature")
        self.assertTrue(result["branch_valid"])
        self.assertTrue(result["file_valid"])


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
