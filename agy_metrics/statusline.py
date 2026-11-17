from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agy_metrics import storage


def _base_dir() -> Path:
    default = Path.home() / ".gemini" / "antigravity-cli" / "hook-metrics"
    return Path(os.environ.get("AGY_METRICS_DIR", str(default)))


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
        conversation_id = data.get("conversation_id") or data.get("conversationId") or "unknown"
        root = storage.turn_dir(_base_dir(), conversation_id)
        cw = data.get("context_window") or data.get("contextWindow")
        if cw:
            storage.write_token_snapshot(root, {
                "total_output_tokens": cw.get("total_output_tokens", cw.get("totalOutputTokens", 0)),
                "total_input_tokens": cw.get("total_input_tokens", cw.get("totalInputTokens", 0)),
            })
        sp = storage.summary_path(root)
        if sp.exists():
            sys.stdout.write(sp.read_text(encoding="utf-8"))
    except Exception:
        pass  # fail-open: never break the CLI
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
