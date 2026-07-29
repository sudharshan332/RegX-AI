"""JP delete auth: creator wins over notification emails list."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_helpers():
    """Import ownership helpers without starting Flask server side-effects heavily."""
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    # Pull only the pure helper block via exec of extracted functions — too heavy.
    # Instead import after stubbing app.run / scheduler if needed.
    # test_flask is large but importable for unit tests in this repo's other tests? none import it.
    # Extract by reading source of the helper functions we need.
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _emails_as_ids(")
    end = src.index("\n@app.route(\"/mcp/regression/dynamic-jp/delete\"")
    ns = {
        "_resolve_jita_user": lambda oid: {},
        "_is_service_account": None,  # filled below from same src
        "logger": mock.Mock(),
    }
    # Also need _is_service_account + markers
    m_start = src.index("_SERVICE_ACCOUNT_MARKERS")
    m_end = src.index("def _emails_as_ids(")
    exec(src[m_start:m_end] + src[start:end], ns)  # noqa: S102
    return ns


class TestJpDeleteCreatorAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def _owner(self, entity):
        # Call through ns dict — do not bind as instance method (would inject self)
        return self.ns["_entity_owner_identity"](entity)

    def test_human_creator_ignores_emails_list(self):
        entity = {
            "created_by": "6a152efdd24d821dbb806804",
            "created_by_user": {
                "user_name": "nagavardhan.pandiri",
                "email": "nagavardhan.pandiri@nutanix.com",
                "display_name": "nagavardhan.pandiri",
            },
            "emails": [
                "shilpa.sattigeri@nutanix.com",
                "thanuja.c@nutanix.com",
                "saisusmitha.beegala@nutanix.com",
            ],
        }
        ids, display = self._owner(entity)
        self.assertIn("nagavardhan.pandiri", ids)
        self.assertIn("nagavardhan.pandiri@nutanix.com", ids)
        self.assertNotIn("shilpa.sattigeri@nutanix.com", ids)
        self.assertNotIn("thanuja.c", ids)
        self.assertIn("nagavardhan", display.lower())

    def test_service_creator_falls_back_to_emails(self):
        entity = {
            "created_by_user": {
                "user_name": "svc.cdp.regression",
                "email": "svc.cdp.regression@nutanix.com",
            },
            "emails": ["swapnil.wankhede@nutanix.com", "teammate@nutanix.com"],
        }
        ids, _ = self._owner(entity)
        self.assertIn("swapnil.wankhede@nutanix.com", ids)
        self.assertIn("swapnil.wankhede", ids)
        self.assertIn("teammate@nutanix.com", ids)

    def test_unresolved_creator_does_not_use_emails(self):
        entity = {
            "emails": ["anyone@nutanix.com"],
            "created_by": None,
            "created_by_user": None,
        }
        ids, display = self._owner(entity)
        self.assertEqual(ids, set())
        self.assertIn("unverified", display.lower())

    def test_bare_string_created_by_resolves_via_user_api(self):
        def fake_resolve(oid):
            if oid == "abc123":
                return {"user_name": "alice", "email": "alice@nutanix.com"}
            return {}

        with mock.patch.dict(self.ns, {"_resolve_jita_user": fake_resolve}):
            ids, display = self._owner({
                "created_by": "abc123",
                "emails": ["bob@nutanix.com"],
            })
        self.assertIn("alice", ids)
        self.assertNotIn("bob@nutanix.com", ids)

    def test_unexpanded_created_by_user_oid(self):
        def fake_resolve(oid):
            if oid == "oid999":
                return {"user_name": "carol", "email": "carol@nutanix.com"}
            return {}

        with mock.patch.dict(self.ns, {"_resolve_jita_user": fake_resolve}):
            ids, _ = self._owner({
                "created_by_user": {"$oid": "oid999"},
                "emails": ["dave@nutanix.com"],
            })
        self.assertIn("carol", ids)
        self.assertNotIn("dave@nutanix.com", ids)


if __name__ == "__main__":
    unittest.main()
