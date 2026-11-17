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
        self.assertTrue(metrics.is_terminal_stop({"event": "Stop", "continuationActive": False}))
        self.assertFalse(metrics.is_terminal_stop({"event": "Stop", "continuationActive": True}))
        self.assertTrue(metrics.is_terminal_stop({"hookEventName": "Stop", "continuationActive": False}))
        self.assertFalse(metrics.is_terminal_stop({"event": "PreInvocation"}))
        self.assertFalse(metrics.is_terminal_stop({
            "event": "Stop", "continuation_active": False, "decision": "continue",
        }))
        self.assertTrue(metrics.is_terminal_stop({
            "event": "Stop", "continuation_active": False, "decision": "end_turn",
        }))
        self.assertTrue(metrics.is_terminal_stop({"event": "Stop"}))

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

    def test_compute_turn_input_tokens_is_snapshot(self):
        events = [
            ev("PreInvocation", invocationNum=0, wallClockMs=100),
            ev("PostInvocation", invocationNum=0, wallClockMs=300),
            ev("Stop", continuation_active=False, decision="end_turn", wallClockMs=500),
        ]
        rec = metrics.compute_turn(
            "conv-1", 1, "m", events,
            {"total_output_tokens": 100, "total_input_tokens": 1890},
            {"total_output_tokens": 412, "total_input_tokens": 3000},
            transcript_start_ms=None,
        )
        self.assertEqual(rec["inputTokens"], 3000)  # snapshot, not the 1110 delta
        self.assertEqual(rec["outputTokens"], 312)  # output stays a delta

    def test_compute_turn_input_tokens_unknown_semantics(self):
        events = [
            ev("PreInvocation", invocationNum=0, wallClockMs=100),
            ev("Stop", continuation_active=False, decision="end_turn", wallClockMs=500),
        ]
        baseline = {"total_output_tokens": 100, "total_input_tokens": 100}
        missing = metrics.compute_turn(
            "c", 1, "m", events, baseline, {"total_output_tokens": 110}, None)
        negative = metrics.compute_turn(
            "c", 1, "m", events, baseline,
            {"total_output_tokens": 110, "total_input_tokens": -1}, None)
        absent = metrics.compute_turn("c", 1, "m", events, baseline, None, None)
        self.assertEqual(missing["inputTokens"], UNKNOWN)
        self.assertEqual(negative["inputTokens"], UNKNOWN)
        self.assertEqual(absent["inputTokens"], UNKNOWN)

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
