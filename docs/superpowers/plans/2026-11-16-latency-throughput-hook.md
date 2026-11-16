# agy 延迟/吞吐量 Hook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an `agy` CLI hook that computes per-turn latency and output throughput using self-recorded wall clocks and a statusline-sidecar token bridge, emitting a per-conversation JSONL archive and a one-line terminal summary.

**Architecture:** One pure `metrics` core (assemble turns from an event log, compute metrics, aggregate) driven by a single testable seam `handle_event(event, base_dir, clock)`; two thin CLI shells (hook command, statusline command) that only decode/encode JSON and delegate to the core. All timing flows through an injectable `Clock`; all file I/O through `storage.py`. Python standard library only.

**Tech Stack:** Python 3.11+ (stdlib: `json`, `pathlib`, `time`, `datetime`, `unittest`, `typing`, `statistics`), `unittest` test runner.

## Global Constraints

- Python standard library **only** — no third-party dependencies.
- `requires-python >= 3.11`.
- Terminology and `Avoid` words MUST follow `GLOSSARY.md`: 会话 Session / 轮次 Turn / 调用 Invocation; Turn Latency / Invocation Duration / TTFT / Output Throughput / Input Token Count. Never call Output Throughput "TPS" or "吞吐率".
- ADR-0001 is binding: token counts come from a **user-built statusline→sidecar bridge**; do not replace with stream-json or fabricate tokens.
- Three sentinels, never mixed: `None` = collection failure (should exist), `"unknown"` = uncomputable in this architecture, number = real value.
- Hook stdout is a strict JSON contract: always exit 0 and print a JSON object. Never print the human summary to stdout.
- `ttftMs` is **always** `"unknown"` — never compute or approximate it.
- Terminal summary is written to a summary sidecar and displayed by the statusline command — never to stderr (undocumented).
- No cross-platform path adaptation; use `pathlib` and the given base directory.

---

### Task 1: Foundation — package, clock, schema primitives

**Files:**
- Create: `pyproject.toml`
- Create: `agy_metrics/__init__.py`
- Create: `agy_metrics/clock.py`
- Create: `agy_metrics/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `Clock` (Protocol with `now_ms() -> int`), `SystemClock`, `FakeClock(start_ms=0, ...)`, `SCHEMA_VERSION: int`, `NULL` (= `None`), `UNKNOWN` (= `"unknown"`), `Completeness` (`Literal["full","partial","empty"]`), `TurnRecord` (TypedDict).

- [ ] **Step 1: Write the failing test for clock and sentinels**

```python
# tests/test_schema.py
import unittest
from agy_metrics.clock import FakeClock
from agy_metrics.schema import NULL, UNKNOWN, SCHEMA_VERSION, Completeness

class TestFoundation(unittest.TestCase):
    def test_fake_clock_is_deterministic(self):
        c = FakeClock(1000)
        self.assertEqual(c.now_ms(), 1000)
        c.advance(250)
        self.assertEqual(c.now_ms(), 1250)
        c.set(5000)
        self.assertEqual(c.now_ms(), 5000)

    def test_sentinels_are_distinct(self):
        self.assertIsNone(NULL)
        self.assertEqual(UNKNOWN, "unknown")
        self.assertNotEqual(NULL, UNKNOWN)

    def test_schema_version(self):
        self.assertEqual(SCHEMA_VERSION, 1)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_schema -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agy_metrics'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project]
name = "agy-metrics-hook"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []
```

```python
# agy_metrics/__init__.py
"""Latency and throughput metrics for the agy CLI hook."""
```

```python
# agy_metrics/clock.py
from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)


class FakeClock:
    def __init__(self, start_ms: int = 0) -> None:
        self._now = start_ms

    def now_ms(self) -> int:
        return self._now

    def advance(self, ms: int) -> None:
        self._now += ms

    def set(self, ms: int) -> None:
        self._now = ms
```

```python
# agy_metrics/schema.py
from __future__ import annotations

from typing import Any, Literal, TypedDict

NULL = None
UNKNOWN = "unknown"
SCHEMA_VERSION = 1

Completeness = Literal["full", "partial", "empty"]


class TurnRecord(TypedDict):
    schemaVersion: int
    conversationId: str
    turnIndex: int
    timestamp: str
    modelName: str
    turnLatencyMs: int | None | str
    invocationCount: int
    invocationDurationsMs: list[int | None]
    activeTimeMs: int
    outputTokens: int | None | str
    inputTokens: int | None | str
    throughputTokensPerSec: float | None | str
    ttftMs: str
    completeness: Completeness
    missing: list[str]
    crossCheck: dict[str, Any]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_schema -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml agy_metrics/__init__.py agy_metrics/clock.py agy_metrics/schema.py tests/test_schema.py
git commit -m "feat: add package, injectable clock, and schema primitives"
```

---

### Task 2: Storage — state layout and all file I/O

**Files:**
- Create: `agy_metrics/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `TurnRecord` from Task 1.
- Produces: functions —
  `turn_dir(base_dir: Path, conversation_id: str) -> Path`;
  `event_log_path(turn_root: Path) -> Path`;
  `archive_path(base_dir: Path, conversation_id: str) -> Path`;
  `tokens_path(turn_root: Path) -> Path`;
  `summary_path(turn_root: Path) -> Path`;
  `append_event(turn_root: Path, event: dict) -> None`;
  `read_events(turn_root: Path) -> list[dict]`;
  `append_record(base_dir: Path, conversation_id: str, record: TurnRecord) -> None`;
  `read_records(base_dir: Path, conversation_id: str) -> list[dict]`;
  `write_token_snapshot(turn_root: Path, snapshot: dict) -> None`;
  `read_token_snapshot(turn_root: Path) -> dict | None`;
  `write_summary(turn_root: Path, text: str) -> None`.

- [ ] **Step 1: Write the failing test for storage round-trips**

```python
# tests/test_storage.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_storage -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agy_metrics.storage'`

- [ ] **Step 3: Write minimal implementation**

```python
# agy_metrics/storage.py
from __future__ import annotations

import json
from pathlib import Path

from agy_metrics.schema import TurnRecord


def turn_dir(base_dir: Path, conversation_id: str) -> Path:
    return base_dir / conversation_id


def event_log_path(turn_root: Path) -> Path:
    return turn_root / "events.jsonl"


def archive_path(base_dir: Path, conversation_id: str) -> Path:
    return base_dir / f"{conversation_id}.jsonl"


def tokens_path(turn_root: Path) -> Path:
    return turn_root / "tokens.json"


def summary_path(turn_root: Path) -> Path:
    return turn_root / "summary.txt"


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append_event(turn_root: Path, event: dict) -> None:
    _append_jsonl(event_log_path(turn_root), event)


def read_events(turn_root: Path) -> list[dict]:
    return _read_jsonl(event_log_path(turn_root))


def append_record(base_dir: Path, conversation_id: str, record: TurnRecord) -> None:
    _append_jsonl(archive_path(base_dir, conversation_id), dict(record))


def read_records(base_dir: Path, conversation_id: str) -> list[dict]:
    return _read_jsonl(archive_path(base_dir, conversation_id))


def write_token_snapshot(turn_root: Path, snapshot: dict) -> None:
    path = tokens_path(turn_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")


def read_token_snapshot(turn_root: Path) -> dict | None:
    path = tokens_path(turn_root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_summary(turn_root: Path, text: str) -> None:
    path = summary_path(turn_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_storage -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agy_metrics/storage.py tests/test_storage.py
git commit -m "feat: add storage layer with namespaced state and JSONL I/O"
```

---

### Task 3: Metrics — pure computation, sentinels, aggregation

**Files:**
- Create: `agy_metrics/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `NULL`, `UNKNOWN`, `TurnRecord` from Task 1.
- Produces:
  `is_terminal_stop(event: dict) -> bool`;
  `pair_invocations(events: list[dict]) -> tuple[list[int | None], int]` returning (durations, active_time_ms);
  `compute_turn(conversation_id, turn_index, model_name, turn_events, baseline_tokens, end_tokens, transcript_start_ms) -> TurnRecord`;
  `aggregate(records: list[TurnRecord]) -> dict`;
  `summary_line(record: TurnRecord, agg: dict) -> str`.

- [ ] **Step 1: Write the failing test for metric formulas and sentinels**

```python
# tests/test_metrics.py
import unittest

from agy_metrics import metrics
from agy_metrics.schema import NULL, UNKNOWN


def ev(name, **kw):
    base = {"event": name, "wallClockMs": 0}
    base.update(kw)
    return base


class TestMetrics(unittest.TestCase):
    def test_terminal_stop_detection(self):
        self.assertTrue(metrics.is_terminal_stop({"event": "Stop", "continuation_active": False}))
        self.assertFalse(metrics.is_terminal_stop({"event": "Stop", "continuation_active": True}))
        self.assertFalse(metrics.is_terminal_stop({"event": "PreInvocation"}))

    def test_pair_invocations_and_active_time(self):
        events = [
            ev("PreInvocation", invocationNum=0, wallClockMs=100),
            ev("PostInvocation", invocationNum=0, wallClockMs=900),
            ev("PreInvocation", invocationNum=1, wallClockMs=1000),
            ev("PostInvocation", invocationNum=1, wallClockMs=1700),
        ]
        durations, active = metrics.pair_invocations(events)
        self.assertEqual(durations, [800, 700])
        self.assertEqual(active, 1500)

    def test_compute_turn_full(self):
        events = [
            ev("PreInvocation", invocationNum=0, wallClockMs=100),
            ev("PostInvocation", invocationNum=0, wallClockMs=900),
            ev("Stop", continuation_active=False, wallClockMs=1200),
        ]
        rec = metrics.compute_turn(
            "conv-1", 1, "gemini-3.6-flash-medium", events,
            {"total_output_tokens": 0, "total_input_tokens": 0},
            {"total_output_tokens": 412, "total_input_tokens": 1890},
            transcript_start_ms=50,
        )
        self.assertEqual(rec["turnLatencyMs"], 1100)
        self.assertEqual(rec["invocationDurationsMs"], [800])
        self.assertEqual(rec["activeTimeMs"], 800)
        self.assertEqual(rec["outputTokens"], 412)
        self.assertEqual(rec["throughputTokensPerSec"], 515.0)
        self.assertEqual(rec["ttftMs"], UNKNOWN)
        self.assertEqual(rec["completeness"], "full")
        self.assertEqual(rec["crossCheck"]["deltaMs"], 50)

    def test_compute_turn_missing_tokens_is_partial(self):
        events = [
            ev("PreInvocation", invocationNum=0, wallClockMs=100),
            ev("Stop", continuation_active=False, wallClockMs=1100),
        ]
        rec = metrics.compute_turn("conv-1", 2, "m", events, None, None, None)
        self.assertEqual(rec["turnLatencyMs"], 1000)
        self.assertEqual(rec["outputTokens"], UNKNOWN)
        self.assertEqual(rec["completeness"], "partial")
        self.assertIn("tokens", rec["missing"])

    def test_compute_turn_no_stop_is_empty(self):
        events = [ev("PreInvocation", invocationNum=0, wallClockMs=100)]
        rec = metrics.compute_turn("conv-1", 3, "m", events, None, None, None)
        self.assertEqual(rec["turnLatencyMs"], NULL)
        self.assertEqual(rec["completeness"], "empty")
        self.assertIn("stop", rec["missing"])

    def test_crosscheck_warning_over_threshold(self):
        events = [
            ev("PreInvocation", invocationNum=0, wallClockMs=10_000),
            ev("Stop", continuation_active=False, wallClockMs=11_000),
        ]
        rec = metrics.compute_turn("c", 1, "m", events, None, None, transcript_start_ms=1_000)
        self.assertTrue(rec["crossCheck"]["warning"])
        self.assertEqual(rec["turnLatencyMs"], 1000)  # authoritative value unchanged

    def test_aggregate_uses_ratio_of_sums(self):
        recs = [
            {"turnLatencyMs": 1000, "activeTimeMs": 800, "outputTokens": 412},
            {"turnLatencyMs": 3000, "activeTimeMs": 200, "outputTokens": 100},
        ]
        agg = metrics.aggregate(recs)  # type: ignore[arg-type]
        self.assertEqual(agg["turnLatency"]["sumMs"], 4000)
        self.assertEqual(agg["turnLatency"]["p50Ms"], 2000)
        self.assertAlmostEqual(agg["throughput"]["tokensPerSec"], 512.0 / 1.0)

    def test_summary_line(self):
        rec = {
            "conversationId": "conv-1", "turnIndex": 2, "turnLatencyMs": 1200,
            "outputTokens": 412, "throughputTokensPerSec": 515.0,
            "inputTokens": 1890, "completeness": "full", "missing": [],
        }
        line = metrics.summary_line(rec, {  # type: ignore[arg-type]
            "turnLatency": {"p50Ms": 1000}
        })
        self.assertIn("turn#2", line)
        self.assertIn("[full]", line)
        self.assertIn("515.0 tok/s", line)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_metrics -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agy_metrics.metrics'`

- [ ] **Step 3: Write minimal implementation**

```python
# agy_metrics/metrics.py
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from agy_metrics.schema import NULL, UNKNOWN, SCHEMA_VERSION, Completeness, TurnRecord

CROSSCHECK_THRESHOLD_MS = 2000


def is_terminal_stop(event: dict) -> bool:
    return (
        event.get("event") == "Stop"
        and event.get("continuation_active") is False
    )


def pair_invocations(events: list[dict]) -> tuple[list[int | None], int]:
    starts: dict[int, int] = {}
    durations: list[int | None] = []
    for e in events:
        name = e.get("event")
        if name == "PreInvocation":
            starts[e["invocationNum"]] = e["wallClockMs"]
        elif name == "PostInvocation":
            num = e["invocationNum"]
            if num in starts:
                durations.append(e["wallClockMs"] - starts.pop(num))
    for _ in starts:
        durations.append(None)
    active = sum(d for d in durations if d is not None)
    return durations, active


def compute_turn(
    conversation_id: str,
    turn_index: int,
    model_name: str,
    turn_events: list[dict],
    baseline_tokens: dict | None,
    end_tokens: dict | None,
    transcript_start_ms: int | None,
) -> TurnRecord:
    pre = [e for e in turn_events if e.get("event") == "PreInvocation"]
    stops = [e for e in turn_events if is_terminal_stop(e)]
    start_ms = min((e["wallClockMs"] for e in pre), default=None)
    end_ms = stops[-1]["wallClockMs"] if stops else None

    if start_ms is not None and end_ms is not None:
        turn_latency: int | None | str = end_ms - start_ms
    else:
        turn_latency = NULL

    durations, active = pair_invocations(turn_events)

    if baseline_tokens and end_tokens:
        out_delta = end_tokens.get("total_output_tokens", 0) - baseline_tokens.get("total_output_tokens", 0)
        in_delta = end_tokens.get("total_input_tokens", 0) - baseline_tokens.get("total_input_tokens", 0)
        if out_delta < 0:
            out_delta = None
        if in_delta < 0:
            in_delta = None
    else:
        out_delta = None
        in_delta = None

    output_tokens: int | None | str = out_delta if out_delta is not None else UNKNOWN
    input_tokens: int | None | str = in_delta if in_delta is not None else UNKNOWN

    if isinstance(output_tokens, int) and active > 0:
        throughput: float | None | str = round(output_tokens / (active / 1000), 1)
    else:
        throughput = UNKNOWN

    cross: dict[str, Any] = {
        "transcriptStart": transcript_start_ms,
        "deltaMs": None,
        "warning": False,
    }
    if start_ms is not None and transcript_start_ms is not None:
        delta = abs(start_ms - transcript_start_ms)
        cross["deltaMs"] = delta
        cross["warning"] = delta > CROSSCHECK_THRESHOLD_MS

    missing: list[str] = []
    if start_ms is None:
        missing.append("pre")
    if end_ms is None:
        missing.append("stop")
    if output_tokens == UNKNOWN or input_tokens == UNKNOWN:
        missing.append("tokens")

    if turn_latency is NULL:
        completeness: Completeness = "empty"
    elif missing:
        completeness = "partial"
    else:
        completeness = "full"

    timestamp = ""
    if start_ms is not None:
        timestamp = datetime.fromtimestamp(start_ms / 1000).astimezone().isoformat()

    return TurnRecord(
        schemaVersion=SCHEMA_VERSION,
        conversationId=conversation_id,
        turnIndex=turn_index,
        timestamp=timestamp,
        modelName=model_name,
        turnLatencyMs=turn_latency,
        invocationCount=len(durations),
        invocationDurationsMs=durations,
        activeTimeMs=active,
        outputTokens=output_tokens,
        inputTokens=input_tokens,
        throughputTokensPerSec=throughput,
        ttftMs=UNKNOWN,
        completeness=completeness,
        missing=missing,
        crossCheck=cross,
    )


def _percentile(sorted_values: list[int], p: float) -> int:
    if not sorted_values:
        return 0
    idx = max(0, math.ceil(p / 100 * len(sorted_values)) - 1)
    return sorted_values[idx]


def aggregate(records: list[TurnRecord]) -> dict:
    latencies = sorted(r["turnLatencyMs"] for r in records if isinstance(r["turnLatencyMs"], int))
    acts = [r["activeTimeMs"] for r in records]
    outs = [r["outputTokens"] for r in records if isinstance(r["outputTokens"], int)]
    total_active = sum(acts)
    total_out = sum(outs)
    return {
        "turnLatency": {
            "p50Ms": _percentile(latencies, 50),
            "p95Ms": _percentile(latencies, 95),
            "sumMs": sum(latencies),
        },
        "throughput": {
            "totalOutputTokens": total_out,
            "totalActiveMs": total_active,
            "tokensPerSec": round(total_out / (total_active / 1000), 1) if total_active > 0 else UNKNOWN,
        },
    }


def summary_line(record: TurnRecord, agg: dict) -> str:
    lat = record["turnLatencyMs"]
    lat_s = f"{lat / 1000:.2f}s" if isinstance(lat, int) else "—"
    p50 = agg["turnLatency"]["p50Ms"]
    p50_s = f"{p50 / 1000:.2f}s" if isinstance(p50, int) else "—"
    out = record["outputTokens"]
    out_s = str(out) if isinstance(out, int) else "—"
    rate = record["throughputTokensPerSec"]
    rate_s = f"{rate} tok/s" if isinstance(rate, float) else "— tok/s"
    inp = record["inputTokens"]
    in_s = f"{inp / 1000:.1f}k" if isinstance(inp, int) else "—"
    comp = record["completeness"]
    miss = f":{','.join(record['missing'])}" if record["missing"] else ""
    return (
        f"agy {record['conversationId']} turn#{record['turnIndex']}  "
        f"{lat_s}  p50 {p50_s}  out {out} tok  {rate_s}  in {in_s}  [{comp}{miss}]"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_metrics -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add agy_metrics/metrics.py tests/test_metrics.py
git commit -m "feat: add metric formulas, three sentinels, and aggregation"
```

---

### Task 4: Core orchestration — the single testable seam

**Files:**
- Create: `agy_metrics/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `Clock` (Task 1), `storage` (Task 2), `metrics` (Task 3), `schema` (Task 1).
- Produces: `handle_event(event: dict, base_dir: Path, clock: Clock) -> TurnRecord | None` — appends the event to the per-conversation event log; on a terminal Stop, assembles the turn, writes the archive record and summary sidecar, returns the record (otherwise `None`). `parse_transcript_start_ms(transcript_path: str) -> int | None` — parses the first `created_at` in a transcript JSONL to epoch ms.

- [ ] **Step 1: Write the failing end-to-end test at the core seam**

```python
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
        self.assertEqual(rec["turnIndex"], 1)
        records = storage.read_records(self.base, "conv-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["outputTokens"], 412)
        summary = storage.summary_path(self.root).read_text(encoding="utf-8")
        self.assertIn("turn#1", summary)
        self.assertIn("[full]", summary)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_core -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agy_metrics.core'`

- [ ] **Step 3: Write minimal implementation**

```python
# agy_metrics/core.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agy_metrics import metrics, storage
from agy_metrics.clock import Clock
from agy_metrics.schema import TurnRecord


def parse_transcript_start_ms(transcript_path: str) -> int | None:
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = __import__("json").loads(line)
                created = obj.get("created_at")
                if created:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    return int(dt.timestamp() * 1000)
    except (OSError, ValueError, KeyError):
        return None
    return None


def handle_event(event: dict, base_dir: Path, clock: Clock) -> TurnRecord | None:
    conversation_id = event.get("conversationId", "unknown")
    root = storage.turn_dir(base_dir, conversation_id)

    events = storage.read_events(root)
    terminal_count = sum(1 for e in events if metrics.is_terminal_stop(e))
    turn_index = terminal_count + 1

    stamped = dict(event)
    stamped["event"] = event.get("hookEventName", event.get("event", ""))
    stamped["wallClockMs"] = clock.now_ms()
    stamped["turnIndex"] = turn_index
    storage.append_event(root, stamped)

    if not metrics.is_terminal_stop(stamped):
        return None

    turn_events = [e for e in storage.read_events(root) if e.get("turnIndex") == turn_index]
    baseline = turn_events[0].get("baselineTokens") if turn_events else None
    end_tokens = storage.read_token_snapshot(root)

    transcript_ms = None
    transcript_path = event.get("transcriptPath")
    if transcript_path:
        transcript_ms = parse_transcript_start_ms(transcript_path)

    record = metrics.compute_turn(
        conversation_id,
        turn_index,
        event.get("modelName", "unknown"),
        turn_events,
        baseline,
        end_tokens,
        transcript_ms,
    )
    storage.append_record(base_dir, conversation_id, record)

    all_records = storage.read_records(base_dir, conversation_id)
    agg = metrics.aggregate(all_records)  # type: ignore[arg-type]
    storage.write_summary(root, metrics.summary_line(record, agg))
    return record
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_core -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agy_metrics/core.py tests/test_core.py
git commit -m "feat: add core orchestration seam with turn assembly and summary"
```

---

### Task 5: Thin CLI shells + config contract

**Files:**
- Create: `agy_metrics/hook_command.py`
- Create: `agy_metrics/statusline.py`
- Create: `config/hooks.example.json`
- Create: `config/statusline.example.sh`
- Test: `tests/test_shells.py`

**Interfaces:**
- Consumes: `core.handle_event` (Task 4), `storage` (Task 2), `SystemClock` (Task 1).
- Produces:
  `hook_command.main() -> int` — reads one JSON object from stdin, calls `core.handle_event` with a `SystemClock` and the base directory from env `AGY_METRICS_DIR` (default `~/.gemini/antigravity-cli/hook-metrics`), prints `{}` to stdout, returns 0.
  `statusline.main() -> int` — reads one JSON object from stdin, writes a token snapshot from `context_window` to the conversation's turn dir, prints the summary sidecar text to stdout if present, returns 0.

- [ ] **Step 1: Write the failing smoke test for both shells**

```python
# tests/test_shells.py
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stdin
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
             redirect_stdin(stdin_with(payload)), redirect_stdout(out):
            code = hook_command.main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), {})

    def test_statusline_writes_tokens_and_prints_summary(self):
        root = storage.turn_dir(self.base, "conv-1")
        storage.write_summary(root, "agy conv-1 turn#1  1.00s  [full]")
        payload = {
            "conversation_id": "conv-1",
            "context_window": {"total_output_tokens": 5, "total_input_tokens": 9},
        }
        out = io.StringIO()
        with patch.dict(os.environ, {"AGY_METRICS_DIR": str(self.base)}), \
             redirect_stdin(stdin_with(payload)), redirect_stdout(out):
            code = statusline.main()
        self.assertEqual(code, 0)
        self.assertEqual(storage.read_token_snapshot(root)["total_output_tokens"], 5)
        self.assertIn("turn#1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_shells -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agy_metrics.hook_command'`

- [ ] **Step 3: Write minimal implementation**

```python
# agy_metrics/hook_command.py
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
```

```python
# agy_metrics/statusline.py
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
        conversation_id = data.get("conversation_id", "unknown")
        root = storage.turn_dir(_base_dir(), conversation_id)
        cw = data.get("context_window")
        if cw:
            storage.write_token_snapshot(root, {
                "total_output_tokens": cw.get("total_output_tokens", 0),
                "total_input_tokens": cw.get("total_input_tokens", 0),
            })
        sp = storage.summary_path(root)
        if sp.exists():
            sys.stdout.write(sp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```json
// config/hooks.example.json
{
  "SessionStart": [{ "hooks": [{ "type": "command", "command": "python -m agy_metrics.hook_command", "timeout": 30 }] }],
  "PreInvocation": [{ "hooks": [{ "type": "command", "command": "python -m agy_metrics.hook_command", "timeout": 30 }] }],
  "PostInvocation": [{ "hooks": [{ "type": "command", "command": "python -m agy_metrics.hook_command", "timeout": 30 }] }],
  "Stop": [{ "hooks": [{ "type": "command", "command": "python -m agy_metrics.hook_command", "timeout": 30 }] }]
}
```

```bash
# config/statusline.example.sh
# statusline command: pipe CLI's JSON into the statusline shell.
# Configure in ~/.gemini/antigravity-cli/settings.json as the statusLine command.
exec python -m agy_metrics.statusline
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_shells -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (all 22 tests)

```bash
git add agy_metrics/hook_command.py agy_metrics/statusline.py config/ tests/test_shells.py
git commit -m "feat: add hook and statusline CLI shells with config examples"
```

---

## Self-Review (completed)

- **Spec coverage:** Problem/Solution → Tasks 1-5; all user stories → core+shells; three sentinels → Task 3; completeness full/partial/empty → Task 3/4; aggregation p50/p95 + ratio-of-sums → Task 3; statusline dual role → Task 5; crossCheck warning → Task 3/4; config contract → Task 5; three assumptions → documented in spec, degradation paths implemented (missing tokens → partial, no stop → empty, transcript parse failure → no crossCheck). No gaps.
- **Placeholder scan:** no "TBD"/"TODO"/"similar to" — every step has concrete code and commands.
- **Type consistency:** `TurnRecord`, `Clock`, `storage.*`, `metrics.*`, `core.handle_event`, `hook_command.main`, `statusline.main` signatures are identical wherever referenced across tasks.
