from __future__ import annotations

from datetime import datetime, timezone
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
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp() * 1000)
    except (OSError, ValueError, KeyError):
        return None
    return None


def handle_event(event: dict, base_dir: Path, clock: Clock) -> TurnRecord | None:
    conversation_id = event.get("conversationId") or event.get("conversation_id") or "unknown"
    root = storage.turn_dir(base_dir, conversation_id)

    events = storage.read_events(root)
    terminal_count = sum(1 for e in events if metrics.is_terminal_stop(e))
    turn_index = terminal_count + 1

    stamped = dict(event)
    stamped["event"] = event.get("hookEventName", event.get("event", ""))
    stamped["wallClockMs"] = clock.now_ms()
    stamped["turnIndex"] = turn_index

    # The token snapshot at the first PreInvocation is the baseline for this
    # turn; the Stop-time snapshot is the end. Capture it on the event so it
    # survives alongside the turn's other stamped events.
    if stamped["event"] == "PreInvocation" and not any(
        e.get("event") == "PreInvocation" and e.get("turnIndex") == turn_index
        for e in events
    ):
        stamped["baselineTokens"] = storage.read_token_snapshot(root)

    storage.append_event(root, stamped)

    if not metrics.is_terminal_stop(stamped):
        return None

    turn_events = [e for e in storage.read_events(root) if e.get("turnIndex") == turn_index]
    baseline = next(
        (
            e.get("baselineTokens")
            for e in turn_events
            if e.get("event") == "PreInvocation" and "baselineTokens" in e
        ),
        None,
    )
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
