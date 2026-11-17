# tests/test_core.py
import json
import tempfile
import unittest
from pathlib import Path

from agy_metrics import core, storage
from agy_metrics.clock import FakeClock


def hook_event(name, conversation_id="conv-1", **kw):
    e = {
        "hookEventName": name,
        "conversationId": conversation_id,
        "modelName": "gemini-3.6-flash-medium",
    }
    e.update(kw)
    return e


class TestCore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.clock = FakeClock(0)
        self.root = storage.turn_dir(self.base, "conv-1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_turn_emits_record_and_summary(self):
        storage.write_token_snapshot(self.root, {"total_output_tokens": 0, "total_input_tokens": 0})
        rec = core.handle_event(hook_event("PreInvocation", invocationNum=0), self.base, self.clock)
        self.assertIsNone(rec)
        self.clock.set(800)
        core.handle_event(hook_event("PostInvocation", invocationNum=0), self.base, self.clock)
        storage.write_token_snapshot(self.root, {"total_output_tokens": 412, "total_input_tokens": 1890})
        self.clock.set(1200)
        rec = core.handle_event(
            hook_event("Stop", continuation_active=False), self.base, self.clock
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec["turnLatencyMs"], 1200)
        self.assertEqual(rec["activeTimeMs"], 800)
        self.assertEqual(rec["toolTimeMs"], 400)
        self.assertEqual(rec["thinkingDurationMs"], "unknown")
        self.assertEqual(rec["turnIndex"], 1)
        records = storage.read_records(self.base, "conv-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["outputTokens"], 412)
        summary = storage.summary_path(self.root).read_text(encoding="utf-8")
        self.assertIn("turn#1", summary)
        self.assertIn("1.20s (m:0.8s t:0.4s)", summary)
        self.assertIn("[full]", summary)

    def test_first_turn_with_session_start_and_camelcase_fields(self):
        storage.write_token_snapshot(self.root, {"total_output_tokens": 0, "total_input_tokens": 0})
        core.handle_event(hook_event("SessionStart"), self.base, self.clock)
        core.handle_event(hook_event("PreInvocation", invocationNum=0), self.base, self.clock)
        self.clock.set(600)
        core.handle_event(hook_event("PostInvocation", invocationNum=0), self.base, self.clock)
        storage.write_token_snapshot(self.root, {"total_output_tokens": 300, "total_input_tokens": 1200})
        self.clock.set(900)
        rec = core.handle_event(
            hook_event("Stop", continuationActive=False), self.base, self.clock
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec["outputTokens"], 300)
        self.assertEqual(rec["completeness"], "full")
        self.assertEqual(rec["missing"], [])

    def test_partial_turn_when_tokens_missing(self):
        core.handle_event(hook_event("PreInvocation", invocationNum=0), self.base, self.clock)
        self.clock.set(1000)
        rec = core.handle_event(
            hook_event("Stop", continuation_active=False), self.base, self.clock
        )
        self.assertEqual(rec["completeness"], "partial")
        self.assertIn("tokens", rec["missing"])

    def test_intermediate_stop_does_not_close_turn(self):
        core.handle_event(hook_event("PreInvocation", invocationNum=0), self.base, self.clock)
        self.clock.set(500)
        mid = core.handle_event(
            hook_event("Stop", continuation_active=True), self.base, self.clock
        )
        self.assertIsNone(mid)
        self.assertEqual(len(storage.read_records(self.base, "conv-1")), 0)

    def test_parse_transcript_start_ms(self):
        path = self.base / "transcript.jsonl"
        path.write_text(
            json.dumps({"step_index": 0, "created_at": "2026-11-16T09:00:00Z"}) + "\n",
            encoding="utf-8",
        )
        ms = core.parse_transcript_start_ms(str(path))
        self.assertIsInstance(ms, int)


if __name__ == "__main__":
    unittest.main()
