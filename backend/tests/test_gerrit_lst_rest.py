"""Tests for Gerrit REST LST CR helpers (no git clone)."""

import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gerrit_lst_cr import (
    GerritLstClient,
    append_missing_tests,
    build_handover_lst_block,
    change_web_url,
    decode_file_content,
    ensure_change_id,
    extract_change_id_footer,
    remove_tests,
)


class TestLstMutations(unittest.TestCase):
    def test_append_skips_existing(self):
        content = "alpha.Test.a\nbeta.Test.b\n"
        new, already, to_add = append_missing_tests(content, ["alpha.Test.a", "gamma.Test.c"])
        self.assertEqual(already, ["alpha.Test.a"])
        self.assertEqual(to_add, ["gamma.Test.c"])
        self.assertIn("gamma.Test.c", new)
        self.assertEqual(new.count("alpha.Test.a"), 1)

    def test_exact_match_ignores_near_names(self):
        content = "pkg.Test.test_foo_bar\n"
        new, already, to_add = append_missing_tests(content, ["pkg.Test.test_foo"])
        self.assertEqual(already, [])
        self.assertEqual(to_add, ["pkg.Test.test_foo"])
        self.assertIn("pkg.Test.test_foo\n", new)
        self.assertIn("pkg.Test.test_foo_bar\n", new)

        removed_content, removed, missing = remove_tests(content, ["pkg.Test.test_foo"])
        self.assertEqual(removed, [])
        self.assertEqual(missing, ["pkg.Test.test_foo"])
        self.assertIn("pkg.Test.test_foo_bar", removed_content)

    def test_remove_exact_lines(self):
        content = "keep.me\nremove.me\nkeep.too\n"
        new, removed, missing = remove_tests(content, ["remove.me", "absent"])
        self.assertEqual(removed, ["remove.me"])
        self.assertEqual(missing, ["absent"])
        self.assertNotIn("remove.me", new)
        self.assertIn("keep.me", new)

    def test_append_adds_owner_header(self):
        content = "summary: x\ntestcases: [\nold.test\n]\n"
        new, already, to_add = append_missing_tests(
            content,
            ["robo.pkg.Test.a"],
            owner="swapnil.wankhede",
            branch="ganges-7.6-stable",
            tickets=["ENG-123"],
            lst_path="test_sets/milestones/7.6.0/CDP/REGRESSION/foo.lst",
        )
        self.assertEqual(to_add, ["robo.pkg.Test.a"])
        self.assertIn("# Owner: swapnil.wankhede, Branch: ganges-7.6-stable, Component: Robo", new)
        self.assertIn("# Tracking ticket: ENG-123", new)
        self.assertNotIn("# Supervisor type:", new)
        # previous last test gets a comma; new last before ] has none
        self.assertIn("old.test,\n", new)
        self.assertIn("robo.pkg.Test.a\n]\n", new)
        self.assertNotIn("robo.pkg.Test.a,\n]", new)

    def test_append_commas_except_last_before_bracket(self):
        content = "testcases: [\nkeep.me\n]\n"
        new, _, to_add = append_missing_tests(
            content, ["a.Test.one", "a.Test.two"], owner="u", branch="master"
        )
        self.assertEqual(to_add, ["a.Test.one", "a.Test.two"])
        self.assertIn("keep.me,\n", new)
        self.assertIn("a.Test.one,\n", new)
        self.assertIn("a.Test.two\n]\n", new)
        self.assertNotIn("a.Test.two,\n", new)

    def test_append_inserts_before_bracket_when_assignee_follows(self):
        content = (
            "summary: Robo\n"
            "testcases: [\n"
            "old.one\n"
            "]\n"
            "assignee: someone\n"
        )
        new, _, to_add = append_missing_tests(
            content, ["robo.a", "robo.b"], owner="swapnil.wankhede", branch="master"
        )
        self.assertEqual(to_add, ["robo.a", "robo.b"])
        self.assertIn("old.one,\n", new)
        self.assertIn("robo.a,\n", new)
        self.assertIn("robo.b\n]\n", new)
        self.assertNotIn("robo.b,\n", new)
        # Must stay inside the list, not appended after assignee
        self.assertLess(new.index("robo.a"), new.index("]\n"))
        self.assertLess(new.index("]\n"), new.index("assignee:"))

    def test_exact_match_ignores_trailing_comma(self):
        content = "pkg.Test.test_foo,\n"
        new, already, to_add = append_missing_tests(content, ["pkg.Test.test_foo"])
        self.assertEqual(already, ["pkg.Test.test_foo"])
        self.assertEqual(to_add, [])
        self.assertEqual(new, content)

        removed_content, removed, missing = remove_tests(
            "testcases: [\npkg.Test.test_foo,\nother.Test.bar\n]\n",
            ["pkg.Test.test_foo"],
        )
        self.assertEqual(removed, ["pkg.Test.test_foo"])
        self.assertIn("other.Test.bar\n]\n", removed_content)
        self.assertNotIn("other.Test.bar,\n", removed_content)

    def test_remove_strips_comma_from_new_last_before_bracket(self):
        content = (
            "testcases: [\n"
            "keep.a,\n"
            "drop.b,\n"
            "drop.c\n"
            "]\n"
        )
        new, removed, missing = remove_tests(content, ["drop.b", "drop.c"])
        self.assertEqual(removed, ["drop.b", "drop.c"])
        self.assertEqual(missing, [])
        self.assertIn("keep.a\n]\n", new)
        self.assertNotIn("keep.a,\n", new)

    def test_append_no_header_when_nothing_to_add(self):
        content = "old.test\n"
        new, already, to_add = append_missing_tests(
            content, ["old.test"], owner="u", branch="master", tickets=["ENG-1"]
        )
        self.assertEqual(to_add, [])
        self.assertEqual(already, ["old.test"])
        self.assertEqual(new, content)
        self.assertNotIn("# Owner:", new)

    def test_remove_drops_owner_block_when_all_tests_gone(self):
        content = (
            "# Owner: Zhijun Zhao, Branch: ganges-7.6-stable, Component: Cassandra\n"
            "# Tracking ticket: ENG-923158\n"
            "# Supervisor type: AHV\n"
            "test.a\n"
            "test.b\n"
            "]\n"
            "keep.after\n"
        )
        new, removed, missing = remove_tests(content, ["test.a", "test.b"])
        self.assertEqual(removed, ["test.a", "test.b"])
        self.assertEqual(missing, [])
        self.assertNotIn("# Owner:", new)
        self.assertNotIn("# Tracking ticket:", new)
        self.assertNotIn("test.a", new)
        self.assertIn("]\n", new)
        self.assertIn("keep.after", new)

    def test_remove_keeps_owner_when_unrelated_sibling_under_same_header(self):
        content = (
            "# Owner: Zhijun Zhao, Branch: ganges-7.6-stable, Component: Cassandra\n"
            "# Tracking ticket: ENG-923158\n"
            "test.a\n"
            "keep.c\n"
        )
        new, removed, missing = remove_tests(content, ["test.a"])
        self.assertEqual(removed, ["test.a"])
        self.assertIn("# Owner:", new)
        self.assertIn("keep.c", new)

    def test_remove_keeps_owner_block_when_sibling_remains(self):
        content = (
            "# Owner: Zhijun Zhao, Branch: ganges-7.6-stable, Component: Cassandra\n"
            "# Tracking ticket: ENG-923158\n"
            "# Supervisor type: AHV\n"
            "test.a\n"
            "test.b\n"
        )
        new, removed, missing = remove_tests(content, ["test.a"])
        self.assertEqual(removed, ["test.a"])
        self.assertIn("# Owner: Zhijun Zhao", new)
        self.assertIn("# Tracking ticket: ENG-923158", new)
        self.assertIn("test.b", new)
        self.assertNotIn("test.a\n", new)

    def test_append_keeps_near_name_siblings(self):
        """Shorter/longer siblings must both be added — never soft-matched away."""
        content = "testcases: [\nold.keep\n]\n"
        selected = [
            "robo.pkg.Test.test_foobar",
            "robo.pkg.Test.test_foo",
            "robo.pkg.Test.test_foo_bar",
        ]
        new, already, to_add = append_missing_tests(
            content, selected, owner="u", branch="master"
        )
        self.assertEqual(already, [])
        self.assertEqual(to_add, selected)
        for name in selected:
            self.assertIn(name, new)

    def test_append_exact_only_does_not_skip_prefix_of_existing(self):
        content = (
            "testcases: [\n"
            "robo.pkg.Test.test_foobar\n"
            "]\n"
        )
        new, already, to_add = append_missing_tests(
            content, ["robo.pkg.Test.test_foo"], owner="u", branch="master"
        )
        self.assertEqual(already, [])
        self.assertEqual(to_add, ["robo.pkg.Test.test_foo"])
        self.assertTrue(
            "robo.pkg.Test.test_foo," in new or "robo.pkg.Test.test_foo\n" in new,
            new,
        )

    def test_resolve_partial_unique_substring(self):
        from gerrit_lst_cr import match_tests_in_lst, remove_tests

        content = (
            "testcases: [\n"
            "cdp.stargate.robo_encryption.x.CompressionSnapshotEncryptionIOIntegrityTest.test_mantle_key_rotation,\n"
            "cdp.stargate.robo_encryption.x.CompressionSnapshotEncryptionIOIntegrityTest.test_background\n"
            "]\n"
        )
        present, missing, resolved_from, ambiguous = match_tests_in_lst(
            content,
            ["CompressionSnapshotEncryptionIOIntegrityTest.test_mantle_ke"],
        )
        self.assertEqual(missing, [])
        self.assertEqual(ambiguous, {})
        self.assertEqual(
            present,
            ["cdp.stargate.robo_encryption.x.CompressionSnapshotEncryptionIOIntegrityTest.test_mantle_key_rotation"],
        )
        self.assertIn(present[0], resolved_from)

        new, removed, not_present = remove_tests(
            content, ["CompressionSnapshotEncryptionIOIntegrityTest.test_mantle_ke"]
        )
        self.assertEqual(removed, present)
        self.assertEqual(not_present, [])
        self.assertNotIn("test_mantle_key_rotation", new)
        self.assertIn("test_background\n]\n", new)

    def test_resolve_strips_quotes_and_comma(self):
        from gerrit_lst_cr import match_tests_in_lst

        content = '"pkg.Test.test_foo",\n'
        present, missing, _, _ = match_tests_in_lst(content, ["pkg.Test.test_foo"])
        self.assertEqual(present, ["pkg.Test.test_foo"])
        self.assertEqual(missing, [])

    def test_exact_match_still_preferred_over_near_name(self):
        from gerrit_lst_cr import match_tests_in_lst

        content = "pkg.Test.test_foo\npkg.Test.test_foo_bar\n"
        present, missing, _, _ = match_tests_in_lst(content, ["pkg.Test.test_foo"])
        self.assertEqual(present, ["pkg.Test.test_foo"])
        self.assertEqual(missing, [])

    def test_change_id_once(self):
        msg = ensure_change_id("Subject\n\nbody")
        self.assertIn("Change-Id: I", msg)
        self.assertEqual(ensure_change_id(msg).count("Change-Id:"), 1)
        first = [ln for ln in msg.splitlines() if ln.startswith("Change-Id:")][0]
        second = [ln for ln in ensure_change_id(msg).splitlines() if ln.startswith("Change-Id:")][0]
        self.assertEqual(first, second)

    def test_reuse_gerrit_assigned_change_id(self):
        assigned = "I" + ("a" * 40)
        msg = ensure_change_id("Subject\n\nbody\n\nChange-Id: I" + ("b" * 40), change_id=assigned)
        self.assertIn("Change-Id: %s" % assigned, msg)
        self.assertEqual(msg.count("Change-Id:"), 1)
        self.assertEqual(
            extract_change_id_footer({"change_id": assigned, "id": "proj~master~%s" % assigned}),
            assigned,
        )

    def test_decode_base64_with_xssi_prefix(self):
        raw = base64.b64encode(b"hello.lst\n").decode("ascii")
        text = ")]}'\n" + raw
        self.assertEqual(decode_file_content(text), "hello.lst\n")

    def test_decode_json_plaintext_string(self):
        body = ')]}\'\n"summary: hello\\ntestcases: [\\na\\n]\\n"'
        self.assertEqual(
            decode_file_content(body),
            "summary: hello\ntestcases: [\na\n]\n",
        )

    def test_change_url(self):
        url = change_web_url("https://nugerrit.ntnxdpro.com", "nutest-py3-tests", 412345)
        self.assertEqual(url, "https://nugerrit.ntnxdpro.com/c/nutest-py3-tests/+/412345")


class _FakeResp(object):
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


class TestGerritLstClient(unittest.TestCase):
    def test_publish_edits_without_clone(self):
        import json as json_mod

        calls = []
        encoded = base64.b64encode(b"old.test\n").decode("ascii")

        def transport(method, url, json=None, data=None, headers=None, auth=None, timeout=None):
            calls.append({"method": method, "url": url, "json": json, "data": data})
            if "/files/" in url and method == "GET":
                return _FakeResp(200, encoded)
            if url.endswith("/a/changes/") and method == "POST":
                cid = "I" + ("c" * 40)
                body = {"_number": 99, "id": "proj~master~%s" % cid, "change_id": cid}
                return _FakeResp(201, ")]}'\n" + json_mod.dumps(body))
            return _FakeResp(200, ")]}'\n{}")

        client = GerritLstClient(
            "https://nugerrit.ntnxdpro.com",
            "user",
            "pw",
            "nutest-py3-tests",
            transport=transport,
        )
        content = client.get_file("master", "test_sets/foo.lst")
        self.assertEqual(content, "old.test\n")
        recorded = []

        def transport2(method, url, json=None, data=None, headers=None, auth=None, timeout=None):
            recorded.append(headers or {})
            return transport(method, url, json=json, data=data, headers=headers, auth=auth, timeout=timeout)

        client2 = GerritLstClient(
            "https://nugerrit.ntnxdpro.com",
            "user",
            "pw",
            "nutest-py3-tests",
            transport=transport2,
        )
        client2.get_file("master", "test_sets/foo.lst")
        self.assertEqual(recorded[0].get("Accept"), "text/plain")
        new, already, to_add = append_missing_tests(content, ["new.test"], owner="u", branch="master")
        self.assertEqual(to_add, ["new.test"])
        result = client.publish_lst_edits("master", "Add tests", {"test_sets/foo.lst": new}, ["rev@nutanix.com"])
        self.assertEqual(result["gerrit_change_id"], "99")
        self.assertEqual(result["change_id"], "I" + ("c" * 40))
        self.assertIn("/+/99", result["gerrit_url"])
        self.assertTrue(any("edit/" in c["url"] and c["method"] == "PUT" for c in calls))
        self.assertTrue(any(c["url"].endswith("edit:publish") for c in calls))
        msg_calls = [c for c in calls if c["url"].endswith("edit:message")]
        self.assertEqual(len(msg_calls), 1)
        self.assertIn("Change-Id: I" + ("c" * 40), msg_calls[0]["json"]["message"])
        put_calls = [c for c in calls if "edit/" in c["url"] and c["method"] == "PUT" and "edit:message" not in c["url"]]
        self.assertTrue(put_calls)
        self.assertEqual(put_calls[0]["data"], new.encode("utf-8"))
        self.assertFalse(any("git" in c["url"] for c in calls))


if __name__ == "__main__":
    unittest.main()
