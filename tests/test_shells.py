import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agy_metrics import hook_command, statusline, storage


def stdin_with(obj):
    return io.StringIO(json.dumps(obj) + "\n")


class TestShells(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hook_command_writes_json_contract(self):
        payload = {
            "hookEventName": "SessionStart",
            "conversationId": "conv-1",
            "modelName": "m",
        }
        out = io.StringIO()
        with patch.dict(os.environ, {"AGY_METRICS_DIR": str(self.base)}), \
             patch("sys.stdin", stdin_with(payload)), redirect_stdout(out):
            code = hook_command.main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), {})

    def test_hook_command_fail_open_on_any_exception(self):
        payload = {
            "hookEventName": "Stop",
            "conversationId": "conv-1",
            "modelName": "m",
        }
        out = io.StringIO()
        with patch.dict(os.environ, {"AGY_METRICS_DIR": str(self.base)}), \
             patch("sys.stdin", stdin_with(payload)), \
             patch("agy_metrics.core.handle_event", side_effect=KeyError("invocationNum")), \
             redirect_stdout(out):
            code = hook_command.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "{}")
        self.assertNotIn("agy ", out.getvalue())

    def test_statusline_fail_open_on_any_exception(self):
        out = io.StringIO()
        with patch.dict(os.environ, {"AGY_METRICS_DIR": str(self.base)}), \
             patch("sys.stdin", stdin_with({"conversation_id": "conv-1"})), \
             patch("agy_metrics.storage.turn_dir", side_effect=KeyError("boom")), \
             redirect_stdout(out):
            code = statusline.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "")

    def test_statusline_writes_tokens_and_prints_summary(self):
        root = storage.turn_dir(self.base, "conv-1")
        storage.write_summary(root, "agy conv-1 turn#1  1.00s  [full]")
        payload = {
            "conversation_id": "conv-1",
            "context_window": {"total_output_tokens": 5, "total_input_tokens": 9},
        }
        out = io.StringIO()
        with patch.dict(os.environ, {"AGY_METRICS_DIR": str(self.base)}), \
             patch("sys.stdin", stdin_with(payload)), redirect_stdout(out):
            code = statusline.main()
        self.assertEqual(code, 0)
        self.assertEqual(storage.read_token_snapshot(root)["total_output_tokens"], 5)
        self.assertIn("turn#1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
