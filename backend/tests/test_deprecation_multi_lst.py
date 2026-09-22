"""Deprecation search uses branch as Sourcegraph rev; CRs accept lst_files."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import create_jwt  # noqa: E402


class CollectLstFilesTests(unittest.TestCase):
    def setUp(self):
        import test_flask as tf

        self.tf = tf

    def test_merges_lst_files_then_lst_file_unique(self):
        out = self.tf._collect_lst_files_from_payload(
            {"lst_files": ["a.lst", "b.lst", "a.lst"], "lst_file": "b.lst"}
        )
        self.assertEqual(out, ["a.lst", "b.lst"])

    def test_lst_file_only(self):
        self.assertEqual(self.tf._collect_lst_files_from_payload({"lst_file": "solo.lst"}), ["solo.lst"])

    def test_empty(self):
        self.assertEqual(self.tf._collect_lst_files_from_payload({}), [])


class DeprecationSearchBranchTests(unittest.TestCase):
    def setUp(self):
        import test_flask as tf

        self.tf = tf
        self.client = tf.app.test_client()
        self.token = create_jwt("alice", "Alice", "alice@nutanix.com")
        self.headers = {"Authorization": "Bearer %s" % self.token, "Content-Type": "application/json"}

    def test_empty_branch_does_not_search_master(self):
        with patch.object(self.tf, "resolve_sourcegraph_token", return_value="tok") as tok, patch.object(
            self.tf, "search_sourcegraph_for_test", return_value=[{"path": "master-only.lst"}]
        ) as search:
            resp = self.client.post(
                "/mcp/regression/deprecation-search",
                json={"q": ["test_foo"]},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body.get("sourcegraph_first_repo"), [])
        self.assertEqual(body.get("branch"), "")
        search.assert_not_called()
        tok.assert_called()

    def test_branch_is_forwarded_as_sourcegraph_rev(self):
        with patch.object(self.tf, "resolve_sourcegraph_token", return_value="tok"), patch.object(
            self.tf, "search_sourcegraph_for_test", return_value=[{"path": "ganges.lst"}]
        ) as search:
            resp = self.client.post(
                "/mcp/regression/deprecation-search",
                json={"q": ["test_foo"], "branch": "7.5.2"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body.get("branch"), "7.5.2")
        self.assertEqual(body["sourcegraph_first_repo"][0]["path"], "ganges.lst")
        self.assertEqual(body["sourcegraph_first_repo"][0]["rev"], "ganges-7.5-stable")
        search.assert_called()
        _args, kwargs = search.call_args
        self.assertEqual(kwargs.get("rev") or (_args[2] if len(_args) > 2 else None), "ganges-7.5-stable")


class SuggestLstFileBranchTests(unittest.TestCase):
    def setUp(self):
        import test_flask as tf

        self.tf = tf
        self.client = tf.app.test_client()
        self.token = create_jwt("alice", "Alice", "alice@nutanix.com")
        self.headers = {"Authorization": "Bearer %s" % self.token, "Content-Type": "application/json"}

    def test_suggest_lst_file_forwards_branch_as_rev(self):
        with patch.object(self.tf, "resolve_sourcegraph_token", return_value="tok"), patch.object(
            self.tf,
            "search_sourcegraph_for_test",
            return_value=[{"path": "test_sets/foo.lst"}],
        ) as search:
            resp = self.client.post(
                "/mcp/regression/suggest-lst-file",
                json={"branch": "7.5.2", "test_names": ["pkg.Test.test_foo"]},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        search.assert_called()
        _args, kwargs = search.call_args
        self.assertEqual(kwargs.get("rev") or (_args[2] if len(_args) > 2 else None), "ganges-7.5-stable")
        body = resp.get_json()
        files = [c.get("lst_file") for c in (body.get("candidates") or [])]
        self.assertIn("test_sets/foo.lst", files)


class DeprecateLstCrPayloadTests(unittest.TestCase):
    def setUp(self):
        import test_flask as tf

        self.tf = tf
        self.client = tf.app.test_client()
        self.token = create_jwt("alice", "Alice", "alice@nutanix.com")
        self.headers = {"Authorization": "Bearer %s" % self.token, "Content-Type": "application/json"}
        self.tmpdir = tempfile.mkdtemp()
        self.dep_path = os.path.join(self.tmpdir, "deprecation_records.json")
        self._prev_dep = os.environ.get("DEPRECATION_RECORDS_PATH")
        os.environ["DEPRECATION_RECORDS_PATH"] = self.dep_path
        with open(self.dep_path, "w", encoding="utf-8") as fh:
            json.dump({"records": []}, fh)

    def tearDown(self):
        if self._prev_dep is None:
            os.environ.pop("DEPRECATION_RECORDS_PATH", None)
        else:
            os.environ["DEPRECATION_RECORDS_PATH"] = self._prev_dep

    def test_manual_cr_includes_all_lst_files(self):
        resp = self.client.post(
            "/mcp/regression/deprecate-lst-cr",
            json={
                "branch": "master",
                "lst_files": ["one.lst", "two.lst"],
                "lst_file": "one.lst",
                "test_names": ["pkg.Test.test_a"],
                "manual_only": True,
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("manual"))
        instr = body.get("instructions") or {}
        self.assertEqual(instr.get("lst_files"), ["one.lst", "two.lst"])
        self.assertEqual(instr.get("lst_file"), "one.lst")
        steps = " ".join(instr.get("manual_steps") or [])
        self.assertIn("one.lst", steps)
        self.assertIn("two.lst", steps)

    def test_deprecation_record_stores_lst_files(self):
        resp = self.client.post(
            "/mcp/regression/deprecation-record",
            json={
                "branch": "master",
                "lst_files": ["one.lst", "two.lst"],
                "lst_file": "one.lst",
                "test_names": ["pkg.Test.test_a"],
                "notes": "saved",
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))
        with open(self.dep_path, encoding="utf-8") as fh:
            saved = json.load(fh)["records"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["lst_file"], "one.lst")
        self.assertEqual(saved[0]["lst_files"], ["one.lst", "two.lst"])


if __name__ == "__main__":
    unittest.main()
