"""Unit tests for NAI client helpers (no live network)."""
import unittest
from unittest.mock import patch

import nai_client


class TestNaiClient(unittest.TestCase):
    def test_resolve_model_aliases(self):
        self.assertEqual(nai_client.resolve_model("nemotron-3-fp4-04"), "nemotron3-fp4-uni")
        self.assertEqual(nai_client.resolve_model("hack-reason"), "nemotron3-fp4-uni")
        self.assertEqual(nai_client.resolve_model(None), "nemotron3-fp4-uni")

    def test_sanitize_api_key_strips_bearer_and_quotes(self):
        self.assertEqual(
            nai_client.sanitize_api_key('Bearer  abc-123 '),
            "abc-123",
        )
        self.assertEqual(nai_client.sanitize_api_key('"abc-123"'), "abc-123")
        self.assertEqual(nai_client.sanitize_api_key("crsr****mnop"), "")

    def test_looks_like_key_name(self):
        self.assertTrue(nai_client.looks_like_key_name("CDP-DPRO-5192-AINTNX-1047"))
        self.assertFalse(nai_client.looks_like_key_name("4f990cff-bbcc-4d15-aa19-9436ce3b8308"))

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

    @patch.object(nai_client, "_validate_embed_key")
    @patch.object(nai_client, "_validate_chat_key")
    def test_validate_api_key_reports_both(self, mock_chat, mock_embed):
        mock_chat.return_value = {"valid": False, "message": "Unauthorized on Reasoning"}
        mock_embed.return_value = {"valid": True, "message": "Embedding OK"}
        result = nai_client.validate_api_key("chat-key", embed_api_key="embed-key")
        self.assertFalse(result["valid"])
        self.assertIn("Reasoning:", result["message"])
        self.assertIn("Embedding:", result["message"])
        self.assertTrue(result["embedding"]["valid"])
        # Embed validated first, then chat (and retry with embed key).
        self.assertGreaterEqual(mock_embed.call_count, 1)
        self.assertGreaterEqual(mock_chat.call_count, 1)

    def test_headers_both_style_includes_authorization(self):
        headers = nai_client._headers("abc-123", auth_style="both")
        self.assertEqual(headers.get("Authorization"), "Bearer abc-123")
        self.assertEqual(headers.get("api-key"), "abc-123")

    def test_chat_base_candidates_corp_first(self):
        nai_client._WORKING_EMBED["base"] = (
            "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/v1"
        )
        nai_client._WORKING_CHAT["base"] = ""
        bases = nai_client._chat_base_candidates()
        self.assertTrue(bases[0].startswith("https://nai-dre.corp."))
        self.assertIn("/gateway/v1", bases[0])
        # Beta must not be preferred just because embeddings authenticated there.
        self.assertNotIn("nai-dre.beta.", bases[0])


if __name__ == "__main__":
    unittest.main()
