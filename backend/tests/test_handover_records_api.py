"""List/search/delete APIs for handover and deprecation records."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import create_jwt  # noqa: E402


class HandoverRecordsApiTests(unittest.TestCase):
    def setUp(self):
        import test_flask as tf

        self.tf = tf
        self.client = tf.app.test_client()
        self.token = create_jwt("alice", "Alice", "alice@nutanix.com")
        self.headers = {"Authorization": "Bearer %s" % self.token, "Content-Type": "application/json"}
        self.tmpdir = tempfile.mkdtemp()
        self.ho_path = os.path.join(self.tmpdir, "handover_records.json")
        self.dep_path = os.path.join(self.tmpdir, "deprecation_records.json")
        self._prev_ho = os.environ.get("HANDOVER_RECORDS_PATH")
        self._prev_dep = os.environ.get("DEPRECATION_RECORDS_PATH")
        os.environ["HANDOVER_RECORDS_PATH"] = self.ho_path
        os.environ["DEPRECATION_RECORDS_PATH"] = self.dep_path
        with open(self.ho_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "records": [
                        {
                            "test_name": "cdp.foo.test_old",
                            "handover_date": "2026-09-01T00:00:00",
                            "lst_file": "old.lst",
                            "handover_tickets": ["ENG-1"],
                            "reviewers": ["alice@nutanix.com"],
                            "notes": "older handover",
                            "by_whom": "alice@nutanix.com",
                        },
                        {
                            "test_name": "cdp.foo.test_new",
                            "handover_date": "2026-09-20T00:00:00",
                            "lst_file": "new.lst",
                            "lst_files": ["new.lst", "extra.lst"],
                            "handover_tickets": ["ENG-2"],
                            "cr_status": "creating",
                            "cr_subject": "Testcase Handover",
                            "by_whom": "bob@nutanix.com",
                        },
                    ]
                },
                fh,
            )
        with open(self.dep_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "records": [
                        {
                            "test_name": "cdp.bar.test_dep",
                            "deprecation_date": "2026-09-21T00:00:00",
                            "lst_file": "dep.lst",
                            "jira_tickets": ["ENG-9"],
                            "notes": "deprecated",
                            "cr_status": "pending_manual",
                            "by_whom": "unknown",
                        }
                    ]
                },
                fh,
            )

    def tearDown(self):
        if self._prev_ho is None:
            os.environ.pop("HANDOVER_RECORDS_PATH", None)
        else:
            os.environ["HANDOVER_RECORDS_PATH"] = self._prev_ho
        if self._prev_dep is None:
            os.environ.pop("DEPRECATION_RECORDS_PATH", None)
        else:
            os.environ["DEPRECATION_RECORDS_PATH"] = self._prev_dep

    def test_handover_records_empty_query_returns_all_newest_first(self):
        resp = self.client.post("/mcp/regression/handover-records", json={}, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        names = [r["test_name"] for r in body["results"]]
        self.assertEqual(names, ["cdp.foo.test_new", "cdp.foo.test_old"])
        self.assertEqual(body["count"], 2)

    def test_handover_records_substring_match(self):
        resp = self.client.post(
            "/mcp/regression/handover-records", json={"q": "test_new"}, headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["test_name"], "cdp.foo.test_new")
        self.assertEqual(body["results"][0]["cr_status"], "creating")

    def test_deprecation_records_list_and_search(self):
        all_resp = self.client.get("/mcp/regression/deprecation-records", headers=self.headers)
        self.assertEqual(all_resp.status_code, 200)
        self.assertEqual(all_resp.get_json()["count"], 1)
        miss = self.client.post(
            "/mcp/regression/deprecation-records", json={"q": "nope"}, headers=self.headers
        )
        self.assertEqual(miss.get_json()["count"], 0)
        hit = self.client.post(
            "/mcp/regression/deprecation-records", json={"q": "test_dep"}, headers=self.headers
        )
        self.assertEqual(hit.get_json()["results"][0]["jira_tickets"], ["ENG-9"])

    def test_list_can_delete_only_for_owner(self):
        resp = self.client.post("/mcp/regression/handover-records", json={}, headers=self.headers)
        flags = {r["test_name"]: r["can_delete"] for r in resp.get_json()["results"]}
        self.assertTrue(flags["cdp.foo.test_old"])
        self.assertFalse(flags["cdp.foo.test_new"])
        dep = self.client.post("/mcp/regression/deprecation-records", json={}, headers=self.headers)
        self.assertFalse(dep.get_json()["results"][0]["can_delete"])

    def test_non_owner_delete_is_forbidden(self):
        resp = self.client.post(
            "/mcp/regression/handover-record-delete",
            json={
                "test_name": "cdp.foo.test_new",
                "handover_date": "2026-09-20T00:00:00",
                "lst_file": "new.lst",
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 403)
        listed = self.client.post("/mcp/regression/handover-records", json={}, headers=self.headers)
        names = [r["test_name"] for r in listed.get_json()["results"]]
        self.assertIn("cdp.foo.test_new", names)

    def test_owner_can_delete_own_record(self):
        resp = self.client.post(
            "/mcp/regression/handover-record-delete",
            json={
                "test_name": "cdp.foo.test_old",
                "handover_date": "2026-09-01T00:00:00",
                "lst_file": "old.lst",
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])

    def test_admin_can_delete_unknown_record(self):
        token = create_jwt("swapnil.wankhede", "Swapnil", "swapnil.wankhede@nutanix.com")
        headers = {"Authorization": "Bearer %s" % token, "Content-Type": "application/json"}
        listed = self.client.post("/mcp/regression/deprecation-records", json={}, headers=headers)
        self.assertTrue(listed.get_json()["results"][0]["can_delete"])
        resp = self.client.post(
            "/mcp/regression/deprecation-record-delete",
            json={
                "test_name": "cdp.bar.test_dep",
                "deprecation_date": "2026-09-21T00:00:00",
                "lst_file": "dep.lst",
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        remaining = self.client.post("/mcp/regression/deprecation-records", json={}, headers=headers)
        self.assertEqual(remaining.get_json()["count"], 0)

    def test_create_stamps_jwt_identity_not_client_body(self):
        resp = self.client.post(
            "/mcp/regression/handover-record",
            json={
                "test_names": ["cdp.foo.test_stamp"],
                "lst_file": "stamp.lst",
                "branch": "master",
                "by_whom": "spoofed@nutanix.com",
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        listed = self.client.post(
            "/mcp/regression/handover-records", json={"q": "test_stamp"}, headers=self.headers
        )
        row = listed.get_json()["results"][0]
        self.assertEqual(row["by_whom"], "alice@nutanix.com")
        self.assertTrue(row["can_delete"])

    def test_save_stores_commit_message_and_test_owner(self):
        ho = self.client.post(
            "/mcp/regression/handover-record",
            json={
                "test_names": ["cdp.foo.test_owner"],
                "lst_file": "test_sets/foo.lst",
                "lst_files": ["test_sets/foo.lst"],
                "branch": "master",
                "commit_message": "Testcase Handover\n\nnote from user",
                "cr_subject": "Testcase Handover",
                "cr_description": "Reviewers               : \n\nnote from user",
                "test_owner": "qa.owner",
                "handover_tickets": ["ENG-1"],
            },
            headers=self.headers,
        )
        self.assertEqual(ho.status_code, 200)
        ho_row = self.client.post(
            "/mcp/regression/handover-records", json={"q": "test_owner"}, headers=self.headers
        ).get_json()["results"][0]
        self.assertEqual(ho_row["commit_message"], "Testcase Handover\n\nnote from user")
        self.assertEqual(ho_row["test_owner"], "qa.owner")
        self.assertEqual(ho_row["cr_subject"], "Testcase Handover")
        self.assertEqual(ho_row["lst_file"], "test_sets/foo.lst")

        dep = self.client.post(
            "/mcp/regression/deprecation-record",
            json={
                "test_names": ["cdp.bar.test_owner"],
                "lst_file": "test_sets/bar.lst",
                "branch": "ganges-7.6-stable",
                "commit_message": "Testcase Deprecation\n\nOwner: qa.owner",
                "cr_subject": "Testcase Deprecation",
                "cr_description": "Owner: qa.owner",
                "test_owner": "qa.owner",
                "jira_tickets": ["ENG-2"],
            },
            headers=self.headers,
        )
        self.assertEqual(dep.status_code, 200)
        dep_row = self.client.post(
            "/mcp/regression/deprecation-records", json={"q": "test_owner"}, headers=self.headers
        ).get_json()["results"][0]
        self.assertEqual(dep_row["commit_message"], "Testcase Deprecation\n\nOwner: qa.owner")
        self.assertEqual(dep_row["test_owner"], "qa.owner")
        self.assertEqual(dep_row["cr_subject"], "Testcase Deprecation")
        self.assertEqual(dep_row["branch"], "ganges-7.6-stable")

    def test_second_save_replaces_unstamped_row(self):
        payload = {
            "test_names": ["cdp.foo.test_again"],
            "lst_file": "test_sets/foo.lst",
            "lst_files": ["test_sets/foo.lst"],
            "branch": "ganges-7.6-stable",
            "commit_message": "first subject\n\nfirst body",
            "test_owner": "qa.owner",
        }
        first = self.client.post("/mcp/regression/handover-record", json=payload, headers=self.headers)
        self.assertEqual(first.status_code, 200)
        payload["commit_message"] = "second subject\n\nsecond body"
        payload["cr_status"] = "creating"
        second = self.client.post("/mcp/regression/handover-record", json=payload, headers=self.headers)
        self.assertEqual(second.status_code, 200)
        rows = [
            r for r in self.tf._load_handover_records()
            if r.get("test_name") == "cdp.foo.test_again"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["commit_message"], "second subject\n\nsecond body")

        self.tf._add_handover_records(
            ["cdp.foo.test_stamped"],
            [],
            "alice@nutanix.com",
            branch="ganges-7.6-stable",
            lst_file="test_sets/foo.lst",
            cr_status="created",
        )
        stored = self.tf._load_handover_records()
        for rec in stored:
            if rec.get("test_name") == "cdp.foo.test_stamped":
                rec["gerrit_change_id"] = "999"
        self.tf._save_handover_records(stored)
        self.tf._add_handover_records(
            ["cdp.foo.test_stamped"],
            [],
            "alice@nutanix.com",
            branch="ganges-7.6-stable",
            lst_file="test_sets/foo.lst",
            commit_message="retry",
            cr_status="creating",
        )
        stamped_rows = [
            r for r in self.tf._load_handover_records()
            if r.get("test_name") == "cdp.foo.test_stamped"
        ]
        self.assertEqual(len(stamped_rows), 2)
        self.assertEqual(sum(1 for r in stamped_rows if r.get("gerrit_change_id") == "999"), 1)

    def test_jp_delete_admin_users_can_delete(self):
        prev = set(self.tf.JP_DELETE_ADMIN_USERS)
        self.tf.JP_DELETE_ADMIN_USERS = set(prev) | {"alice"}
        try:
            resp = self.client.post(
                "/mcp/regression/deprecation-record-delete",
                json={
                    "test_name": "cdp.bar.test_dep",
                    "deprecation_date": "2026-09-21T00:00:00",
                    "lst_file": "dep.lst",
                },
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.get_json()["success"])
        finally:
            self.tf.JP_DELETE_ADMIN_USERS = prev

    def test_deprecation_record_delete(self):
        token = create_jwt("sudharshan.musali", "Sudharshan", "sudharshan.musali@nutanix.com")
        headers = {"Authorization": "Bearer %s" % token, "Content-Type": "application/json"}
        resp = self.client.post(
            "/mcp/regression/deprecation-record-delete",
            json={
                "test_name": "cdp.bar.test_dep",
                "deprecation_date": "2026-09-21T00:00:00",
                "lst_file": "dep.lst",
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        listed = self.client.post(
            "/mcp/regression/deprecation-records", json={}, headers=headers
        )
        self.assertEqual(listed.get_json()["count"], 0)

    def test_stamp_newest_batch_with_cr(self):
        self.tf._add_handover_records(
            ["cdp.foo.test_a", "cdp.foo.test_b"],
            [],
            "alice@nutanix.com",
            branch="7.5.2",
            lst_file="test_sets/milestones/7.5/CDP/foo.lst",
            lst_files=["test_sets/milestones/7.5/CDP/foo.lst"],
            cr_status="creating",
        )
        self.tf._add_handover_records(
            ["cdp.foo.test_a"],
            [],
            "alice@nutanix.com",
            branch="7.5.2",
            lst_file="test_sets/milestones/7.5/CDP/foo.lst",
            cr_status="creating",
        )
        stamped = self.tf._stamp_records_with_cr(
            "handover",
            ["cdp.foo.test_a", "cdp.foo.test_b"],
            ["7.5.2", "ganges-7.5-stable"],
            ["test_sets/milestones/7.5/CDP/foo.lst"],
            "606185",
            "https://nugerrit.ntnxdpro.com/c/nutest-py3-tests/+/606185",
        )
        self.assertEqual(stamped, 1)
        rows = self.tf._load_handover_records()
        stamped_rows = [r for r in rows if r.get("gerrit_change_id") == "606185"]
        self.assertEqual(len(stamped_rows), 1)
        self.assertEqual(stamped_rows[0]["test_name"], "cdp.foo.test_a")
        self.assertEqual(stamped_rows[0]["cr_status"], "created")
        older = [r for r in rows if r.get("test_name") == "cdp.foo.test_b"]
        self.assertTrue(older)
        self.assertFalse(older[0].get("gerrit_change_id"))
