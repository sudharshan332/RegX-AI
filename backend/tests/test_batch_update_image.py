"""Unit tests for Image Branch job-profile batch updates."""

import os
import unittest


def _load_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("# JITA PUT /job_profiles/:id only accepts these image_build_selection values.")
    end = src.index('@app.route("/mcp/regression/run-plan/<run_plan_id>/batch-update"')
    ns = {}
    exec(src[start:end], ns)  # noqa: S102
    return ns


class TestApplyImageComponentUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep helpers in a dict so unittest does not bind them as methods.
        cls.ns = _load_helpers()

    def _apply(self, profile, comp_data):
        return self.ns["_apply_image_component_update"](profile, comp_data)

    def _prepare(self, profile):
        return self.ns["_prepare_jita_jp_put_payload"](profile)

    def test_updates_branch_and_build_type_only(self):
        profile = {"image_branch": "old-branch", "image_build_type": "None"}
        self._apply(profile, {
            "branch": "ganges-7.6.0.6-stable",
            "build_type": "release",
        })
        self.assertEqual(profile["image_branch"], "ganges-7.6.0.6-stable")
        self.assertEqual(profile["image_build_type"], "release")
        self.assertNotIn("image_build_selection", profile)

    def test_by_tag_sets_selection_and_nulls_commit(self):
        profile = {
            "image_commit": "abc123",
            "image_gbn": 111,
            "image_build_selection": "By Commit",
        }
        self._apply(profile, {
            "update_type": "tag",
            "tag": "By Latest Smoke Passed",
        })
        self.assertEqual(profile["image_build_selection"], "By Latest Smoke Passed")
        self.assertIsNone(profile["image_commit"])
        self.assertNotIn("image_gbn", profile)

    def test_by_commit_sets_commit_and_gbn(self):
        profile = {"image_build_selection": "By Latest Smoke Passed"}
        self._apply(profile, {
            "update_type": "commit",
            "commit_id": "fd96efb85c11ac75f282d51dce06e04a279bad2d",
            "gbn": "1786602592",
        })
        self.assertEqual(profile["image_build_selection"], "By Commit")
        self.assertEqual(profile["image_commit"], "fd96efb85c11ac75f282d51dce06e04a279bad2d")
        self.assertEqual(profile["image_gbn"], 1786602592)

    def test_empty_fields_leave_existing_values(self):
        profile = {
            "image_branch": "keep-me",
            "image_build_type": "opt",
            "image_commit": "oldcommit",
            "image_gbn": 99,
        }
        self._apply(profile, {"branch": "", "build_type": "", "update_type": ""})
        self.assertEqual(profile["image_branch"], "keep-me")
        self.assertEqual(profile["image_build_type"], "opt")
        self.assertEqual(profile["image_commit"], "oldcommit")
        self.assertEqual(profile["image_gbn"], 99)

    def test_put_payload_matches_jita_ui_shape(self):
        profile = {
            "_id": {"$oid": "6a7c7400d24d8207efaa4581"},
            "created_at": {"$date": 1},
            "updated_at": {"$date": 2},
            "created_by_user": {"$oid": "abc"},
            "last_triggered": {"$date": 3},
            "scheduled_jobs": [],
            "v": 3,
            "name": "LCM_CDP_Regression_Upgrade",
            "image_branch": "ganges-7.5-stable",
            "image_build_type": "release",
            "image_build_selection": "By Latest Build Passed",
            "image_commit": "",
            "git": {"branch": "ganges-7.6.0.6-stable", "repo": "main"},
        }
        payload = self._prepare(profile)
        self.assertNotIn("_id", payload)
        self.assertNotIn("created_at", payload)
        self.assertNotIn("scheduled_jobs", payload)
        self.assertEqual(payload["image_branch"], "ganges-7.5-stable")
        self.assertEqual(payload["image_build_type"], "release")
        self.assertEqual(payload["image_build_selection"], "By Latest Build Passed")
        self.assertIsNone(payload["image_commit"])
        self.assertEqual(payload["v"], 3)
        self.assertEqual(payload["git"]["branch"], "ganges-7.6.0.6-stable")

    def test_put_payload_strips_invalid_image_selection(self):
        payload = self._prepare({
            "name": "jp",
            "image_build_selection": "None",
            "image_build_type": "None",
        })
        self.assertNotIn("image_build_selection", payload)
        self.assertEqual(payload["image_build_type"], "None")


if __name__ == "__main__":
    unittest.main()
