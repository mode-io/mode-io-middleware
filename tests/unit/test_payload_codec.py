#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT
sys.path.insert(0, str(PACKAGE_DIR))

from modeio_middleware.core.payload_codec import (  # noqa: E402
    denormalize_response_payload,
    normalize_response_payload,
)


class TestPayloadCodec(unittest.TestCase):
    def test_anthropic_response_roundtrip_preserves_top_level_content_blocks(self):
        response_body = {
            "id": "msg_example",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [
                {
                    "type": "text",
                    "text": "Hello! How can I help you today?",
                }
            ],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 8,
                "output_tokens": 10,
            },
        }

        normalized = normalize_response_payload(
            endpoint_kind="anthropic_messages",
            source="anthropic_gateway",
            response_body=response_body,
            connector_context={},
        )

        roundtrip = denormalize_response_payload(normalized)

        self.assertEqual(roundtrip["content"][0]["text"], response_body["content"][0]["text"])
        self.assertEqual(roundtrip["role"], response_body["role"])
        self.assertEqual(roundtrip["stop_reason"], response_body["stop_reason"])


if __name__ == "__main__":
    unittest.main()
