"""Unit tests for NAI client helpers (no live network)."""
import unittest
from unittest.mock import patch

import nai_client


class TestNaiClient(unittest.TestCase):
    def test_resolve_model_aliases(self):
        self.assertEqual(nai_client.resolve_model("nemotron-3-fp4-04"), "nemotron3-fp4-uni")
        self.assertEqual(nai_client.resolve_model("hack-reason"), "nemotron3-fp4-uni")
        self.assertEqual(nai_client.resolve_model(None), "nemotron3-fp4-uni")

    def test_cosine_similarity(self):
        self.assertAlmostEqual(nai_client.cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(nai_client.cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_parse_json_object(self):
        self.assertEqual(
            nai_client.parse_json_object('{"root_cause": "x", "classification": "Test Issue"}'),
            {"root_cause": "x", "classification": "Test Issue"},
        )
        self.assertEqual(
            nai_client.parse_json_object('noise ```json\n{"a": 1}\n```'),
            {"a": 1},
        )

    @patch.object(nai_client, "chat_completions")
    def test_chat_text(self, mock_chat):
        mock_chat.return_value = {
            "choices": [{"message": {"content": " hello "}}],
        }
        self.assertEqual(
            nai_client.chat_text("sys", "user", api_key="test-key"),
            "hello",
        )
        args, kwargs = mock_chat.call_args
        self.assertEqual(kwargs["api_key"], "test-key")
        self.assertEqual(args[0][0]["role"], "system")


if __name__ == "__main__":
    unittest.main()
