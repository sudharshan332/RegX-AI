"""Unit tests for login team config loading and JWT team claims."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import (
    create_jwt,
    decode_jwt,
    get_default_team,
    load_teams_config,
    validate_team,
)


class TestAuthTeams(unittest.TestCase):
    def test_load_teams_config_includes_cdp_teams(self):
        config = load_teams_config()
        team_ids = [t["id"] for t in config.get("teams", [])]
        self.assertIn("CDP_FT", team_ids)
        self.assertIn("CDP_ST", team_ids)
        self.assertTrue(config.get("default_team"))

    def test_validate_team(self):
        self.assertTrue(validate_team("CDP_FT"))
        self.assertTrue(validate_team("CDP_ST"))
        self.assertFalse(validate_team("NOT_A_TEAM"))
        self.assertFalse(validate_team(""))

    def test_jwt_embeds_selected_team(self):
        token = create_jwt("alice", "Alice", "alice@example.com", team="CDP_ST")
        payload = decode_jwt(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["team"], "CDP_ST")
        self.assertEqual(payload["sub"], "alice")

    def test_jwt_falls_back_to_default_team(self):
        token = create_jwt("bob", team="bogus")
        payload = decode_jwt(token)
        self.assertEqual(payload["team"], get_default_team())


if __name__ == "__main__":
    unittest.main()
