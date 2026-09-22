"""Phase 3 Deep AI chat intent helpers."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load only the intent functions without importing full Flask app.
_SRC = open(os.path.join(os.path.dirname(__file__), "..", "test_flask.py"), encoding="utf-8").read()
_NS = {"re": re}
for _name in (
    "is_create_eng_ticket_intent",
    "is_flux_quick_fix_intent",
    "is_confirm_eng_ticket_intent",
    "extract_eng_ticket_keys",
):
    _m = re.search(rf"^def {_name}\(.*?(?=^def |\Z)", _SRC, re.M | re.S)
    assert _m, _name
    exec(compile(_m.group(0), _name, "exec"), _NS)


class TestDeepAiPhase3Intents(unittest.TestCase):
    def test_create_eng_intent(self):
        self.assertTrue(_NS["is_create_eng_ticket_intent"]("create eng ticket"))
        self.assertTrue(_NS["is_create_eng_ticket_intent"]("Creat Eng"))
        self.assertTrue(_NS["is_create_eng_ticket_intent"]("creat eng"))
        self.assertFalse(_NS["is_create_eng_ticket_intent"]("open ticket ENG-1"))

    def test_flux_intent(self):
        self.assertTrue(_NS["is_flux_quick_fix_intent"]("trigger flux quick fix"))
        self.assertFalse(_NS["is_flux_quick_fix_intent"]("summarize triage"))

    def test_extract_keys(self):
        self.assertEqual(
            _NS["extract_eng_ticket_keys"]("see ENG-9 and eng-2"),
            ["ENG-9", "ENG-2"],
        )


if __name__ == "__main__":
    unittest.main()
