from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from agy_metrics.schema import NULL, UNKNOWN, SCHEMA_VERSION, Completeness, TurnRecord

CROSSCHECK_THRESHOLD_MS = 2000


def is_terminal_stop(event: dict) -> bool:
    name = event.get("event") or event.get("hookEventName")
    continuation = event.get("continuationActive")
    if continuation is None:
        continuation = event.get("continuation_active", False)
    return (
        name == "Stop"
        and continuation is False
        and event.get("decision") != "continue"
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
        if out_delta < 0:
            out_delta = None
    else:
        out_delta = None

    # Input Token Count is the bridge snapshot read at Stop time, not a
    # between-turn delta; it is reported separately from output throughput.
    snapshot_in = end_tokens.get("total_input_tokens") if end_tokens else None
    input_tokens: int | None | str
    if snapshot_in is None or snapshot_in < 0:
        input_tokens = UNKNOWN
    else:
        input_tokens = snapshot_in

    output_tokens: int | None | str = out_delta if out_delta is not None else UNKNOWN

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
        timestamp = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).astimezone().isoformat()

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
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = p / 100 * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo))


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
        f"{lat_s}  p50 {p50_s}  out {out_s} tok  {rate_s}  in {in_s}  [{comp}{miss}]"
    )
