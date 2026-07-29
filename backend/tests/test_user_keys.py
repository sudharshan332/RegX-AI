"""Tests for per-user API key store used by User Settings."""
import os
import tempfile
import unittest

from user_keys import (
    get_user_key,
    get_user_keys_masked,
    mask_secret,
    reset_fernet_cache_for_tests,
    upsert_user_keys,
)


class TestUserKeys(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._tmpdir.name, "user_api_keys.json")
        self._fernet = os.path.join(self._tmpdir.name, "user_api_keys.fernet")
        os.environ["REGX_USER_KEYS_FILE"] = self._path
        os.environ["REGX_USER_KEYS_FERNET_FILE"] = self._fernet
        os.environ.pop("SECRET_KEY", None)
        os.environ.pop("REGX_SECRET_KEY", None)
        os.environ.pop("REGX_USER_KEYS_SECRET", None)
        reset_fernet_cache_for_tests()

    def tearDown(self):
        self._tmpdir.cleanup()
        os.environ.pop("REGX_USER_KEYS_FILE", None)
        os.environ.pop("REGX_USER_KEYS_FERNET_FILE", None)
        reset_fernet_cache_for_tests()

    def test_upsert_and_masked_roundtrip(self):
        masked = upsert_user_keys(
            "alice",
            {"atlassian_jira_token": "super-secret-jira-token-value"},
        )
        self.assertIn("****", masked["atlassian_jira_token"])
        self.assertNotIn("super-secret", masked["atlassian_jira_token"])
        raw = get_user_key("alice", "atlassian_jira_token")
        self.assertEqual(raw, "super-secret-jira-token-value")
        self.assertEqual(get_user_key("Alice", "atlassian_jira_token"), raw)

    def test_survives_secret_key_change(self):
        """Persisted fernet file keeps tokens readable without SECRET_KEY."""
        upsert_user_keys("carol", {"atlassian_jira_token": "jira-pat-abc-12345"})
        reset_fernet_cache_for_tests()
        os.environ["SECRET_KEY"] = "totally-different-random-secret"
        reset_fernet_cache_for_tests()
        self.assertEqual(
            get_user_key("carol", "atlassian_jira_token"),
            "jira-pat-abc-12345",
        )

    def test_skips_masked_values(self):
        upsert_user_keys("bob", {"cursor_api_key": "crsr_abcdefghijklmnop"})
        with self.assertRaises(ValueError):
            upsert_user_keys("bob", {"cursor_api_key": "crsr****mnop"})
        self.assertEqual(get_user_key("bob", "cursor_api_key"), "crsr_abcdefghijklmnop")

    def test_mask_shape(self):
        self.assertEqual(mask_secret("abcdefghij"), "abcd****ghij")
        view = get_user_keys_masked("nobody")
        self.assertEqual(view["atlassian_jira_token"], "")


if __name__ == "__main__":
    unittest.main()
