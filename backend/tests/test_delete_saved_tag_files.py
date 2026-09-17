"""Removing a saved failed-analysis tag deletes both per-tag JSON caches."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import create_jwt  # noqa: E402


class TestDeleteSavedTagFiles(unittest.TestCase):
    def setUp(self):
        import test_flask as tf

        self.tf = tf
        self.client = tf.app.test_client()
        self.token = create_jwt("alice", "Alice", "alice@nutanix.com")
        self.headers = {"Authorization": "Bearer %s" % self.token}
        self.tmpdir = tempfile.mkdtemp()
        self._prev_override = os.environ.get("REGX_TEAM_DATA_DIR")
        os.environ["REGX_TEAM_DATA_DIR"] = self.tmpdir

    def tearDown(self):
        if self._prev_override is None:
            os.environ.pop("REGX_TEAM_DATA_DIR", None)
        else:
            os.environ["REGX_TEAM_DATA_DIR"] = self._prev_override

    def test_delete_saved_tag_removes_analysis_and_triage_json(self):
        tag = "7.6.0.1_RC1"
        fa = os.path.join(self.tmpdir, "failed_analysis_7.6.0.1_RC1.json")
        ta = os.path.join(self.tmpdir, "triage_accuracy_data_7.6.0.1_RC1.json")
        tags_path = os.path.join(self.tmpdir, "failed_analysis_saved_tags.json")
        with open(fa, "w", encoding="utf-8") as fh:
            json.dump({"tag": tag, "results": []}, fh)
        with open(ta, "w", encoding="utf-8") as fh:
            json.dump({"tag": tag, "rows": []}, fh)
        with open(tags_path, "w", encoding="utf-8") as fh:
            json.dump({"tags": [{"name": tag, "added_at": "2026-01-01T00:00:00Z"}]}, fh)

        resp = self.client.delete(
            "/mcp/regression/failed-analysis/saved-tags/%s" % tag,
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("success"))
        names = [t["name"] if isinstance(t, dict) else t for t in body.get("tags") or []]
        self.assertNotIn(tag, names)
        self.assertFalse(os.path.exists(fa))
        self.assertFalse(os.path.exists(ta))

    def test_helpers_delete_team_and_legacy_copies(self):
        team_dir = tempfile.mkdtemp()
        legacy_dir = tempfile.mkdtemp()
        filename = "failed_analysis_7.6.0.1_RC1.json"
        team_file = os.path.join(team_dir, filename)
        legacy_file = os.path.join(legacy_dir, filename)
        with open(team_file, "w", encoding="utf-8") as fh:
            fh.write("{}")
        with open(legacy_file, "w", encoding="utf-8") as fh:
            fh.write("{}")

        orig_team = self.tf._get_team_data_dir
        orig_legacy = self.tf._get_legacy_data_dir
        orig_env = os.environ.pop("REGX_TEAM_DATA_DIR", None)
        try:
            self.tf._get_team_data_dir = lambda create=False: team_dir
            self.tf._get_legacy_data_dir = lambda: legacy_dir
            self.tf.delete_failed_analysis_results("7.6.0.1_RC1")
            self.assertFalse(os.path.exists(team_file))
            self.assertFalse(os.path.exists(legacy_file))
        finally:
            self.tf._get_team_data_dir = orig_team
            self.tf._get_legacy_data_dir = orig_legacy
            if orig_env is not None:
                os.environ["REGX_TEAM_DATA_DIR"] = orig_env
            else:
                os.environ["REGX_TEAM_DATA_DIR"] = self.tmpdir

    def test_invalidate_does_not_delete_unrelated_legacy_shared_file(self):
        legacy_dir = tempfile.mkdtemp()
        shared = os.path.join(legacy_dir, "triage_accuracy_data.json")
        with open(shared, "w", encoding="utf-8") as fh:
            json.dump({"tag": "other_tag"}, fh)
        orig_legacy = self.tf._get_legacy_data_dir
        orig_env = os.environ.pop("REGX_TEAM_DATA_DIR", None)
        try:
            self.tf._get_legacy_data_dir = lambda: legacy_dir
            self.tf.invalidate_triage_accuracy_cache("7.6.0.1_RC1")
            self.assertTrue(os.path.exists(shared))
        finally:
            self.tf._get_legacy_data_dir = orig_legacy
            if orig_env is not None:
                os.environ["REGX_TEAM_DATA_DIR"] = orig_env
            else:
                os.environ["REGX_TEAM_DATA_DIR"] = self.tmpdir

    def test_delete_config_tag_removes_triage_accuracy_json(self):
        tag = "7.6.0.1_RC1"
        ta = os.path.join(self.tmpdir, "triage_accuracy_data_7.6.0.1_RC1.json")
        cfg = os.path.join(self.tmpdir, "regression_config.json")
        with open(ta, "w", encoding="utf-8") as fh:
            json.dump({"tag": tag, "testcases": []}, fh)
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({
                "input_mode": "tag",
                "tag": tag,
                "default_tag": tag,
                "added_tags": [tag],
                "task_ids": [],
                "tag_extra_task_ids": {},
            }, fh)

        resp = self.client.delete(
            "/mcp/regression/config/tags",
            headers=self.headers,
            query_string={"tag": tag},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(tag, resp.get_json().get("added_tags") or [])
        self.assertFalse(os.path.exists(ta))


class TestDeleteTestcaseMgmtBranchFiles(unittest.TestCase):
    def setUp(self):
        import test_flask as tf

        self.tf = tf
        self.client = tf.app.test_client()
        self.token = create_jwt("alice", "Alice", "alice@nutanix.com")
        self.headers = {"Authorization": "Bearer %s" % self.token}
        self.tmpdir = tempfile.mkdtemp()
        self._prev_tc_dir = tf.TESTCASE_MGMT_DATA_DIR
        tf.TESTCASE_MGMT_DATA_DIR = self.tmpdir

    def tearDown(self):
        self.tf.TESTCASE_MGMT_DATA_DIR = self._prev_tc_dir

    def test_delete_branch_removes_testcase_management_json(self):
        branch = "7.7"
        paths = [
            os.path.join(self.tmpdir, "testcase_management_7.7_CDP.json"),
            os.path.join(self.tmpdir, "testcase_management_ganges-7.7-stable_CDP.json"),
            os.path.join(self.tmpdir, "testcase_management_7.7_AHV.json"),
        ]
        for path in paths:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"branch": branch, "testcases": []}, fh)

        resp = self.client.delete(
            "/mcp/regression/testcase-mgmt/branches",
            headers=self.headers,
            query_string={"branch": branch},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("success"))
        self.assertEqual(body.get("branch"), "7.7")
        for path in paths:
            self.assertFalse(os.path.exists(path), path)


if __name__ == "__main__":
    unittest.main()
