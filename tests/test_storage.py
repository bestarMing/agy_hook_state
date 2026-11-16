import json
import tempfile
import unittest
from pathlib import Path

from agy_metrics import storage


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = storage.turn_dir(self.base, "conv-1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_event_log_append_and_read(self):
        storage.append_event(self.root, {"event": "PreInvocation", "turnIndex": 1})
        storage.append_event(self.root, {"event": "Stop", "turnIndex": 1})
        events = storage.read_events(self.root)
        self.assertEqual([e["event"] for e in events], ["PreInvocation", "Stop"])

    def test_archive_append_and_read(self):
        rec = {"turnIndex": 1, "turnLatencyMs": 100}
        storage.append_record(self.base, "conv-1", rec)  # type: ignore[arg-type]
        records = storage.read_records(self.base, "conv-1")
        self.assertEqual(records, [rec])

    def test_token_snapshot_round_trip(self):
        self.assertIsNone(storage.read_token_snapshot(self.root))
        storage.write_token_snapshot(
            self.root, {"total_output_tokens": 10, "total_input_tokens": 20}
        )
        snap = storage.read_token_snapshot(self.root)
        self.assertEqual(snap["total_output_tokens"], 10)

    def test_summary_write(self):
        storage.write_summary(self.root, "agy conv-1 turn#1  1.00s  [full]")
        self.assertEqual(
            storage.summary_path(self.root).read_text(encoding="utf-8"),
            "agy conv-1 turn#1  1.00s  [full]",
        )

    def test_paths_are_namespaced_by_conversation(self):
        self.assertIn("conv-1", str(self.root))
        self.assertNotEqual(
            storage.archive_path(self.base, "conv-1"),
            storage.archive_path(self.base, "conv-2"),
        )


if __name__ == "__main__":
    unittest.main()
