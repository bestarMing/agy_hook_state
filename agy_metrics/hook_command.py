from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agy_metrics import core
from agy_metrics.clock import SystemClock


def _base_dir() -> Path:
    default = Path.home() / ".gemini" / "antigravity-cli" / "hook-metrics"
    return Path(os.environ.get("AGY_METRICS_DIR", str(default)))


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
        core.handle_event(event, _base_dir(), SystemClock())
    except (ValueError, OSError):
        pass  # fail-open: never break the CLI
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
