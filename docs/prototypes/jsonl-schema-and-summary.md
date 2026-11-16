# PROTOTYPE — JSONL schema & one-line terminal summary

> **Throwaway prototype** for ticket #6 "定 JSONL schema、文件路径与终端呈现". Not production. Captured on branch `prototype/jsonl-schema` (never merged). Its job is to make the data shape concrete so you can react to it.
>
> Assumption on branch choice: this ticket answers "what should this look like" (a data shape), not "does this state model feel right", so the artifact is concrete sample records + summary lines rather than the interactive HTML of the LOGIC/UI prototype branches.

All values below are illustrative but concrete, following the locked decisions: record unit = **轮次 Turn** (T2); fields per T5 algorithm; token data via ADR-0001 sidecar bridge.

---

## 1. Archive JSONL — one record per turn

File: `~/.gemini/antigravity-cli/hook-metrics/<conversationId>.jsonl` (one file per conversation; see §4).

**Case A — full turn** (3 invocations, tokens present):

```json
{"schemaVersion":1,"conversationId":"c-7f3a","turnIndex":2,"timestamp":"2026-11-16T09:31:02Z","modelName":"gemini-3.6-flash-medium","turnLatencyMs":7240,"invocationCount":3,"invocationDurationsMs":[1200,1850,1770],"activeTimeMs":4820,"outputTokens":412,"inputTokens":1890,"throughputTokensPerSec":85.5,"ttftMs":"unknown","completeness":"full","missing":[],"crossCheck":{"transcriptStart":"2026-11-16T09:31:01Z","deltaMs":1000,"warning":null}}
```

**Case B — partial turn** (turn latencies captured, token sidecar not written this turn — throttle / 30-failure disable):

```json
{"schemaVersion":1,"conversationId":"c-7f3a","turnIndex":3,"timestamp":"2026-11-16T09:33:41Z","modelName":"gemini-3.6-flash-medium","turnLatencyMs":5210,"invocationCount":2,"invocationDurationsMs":[2400,2810],"activeTimeMs":5210,"outputTokens":"unknown","inputTokens":"unknown","throughputTokensPerSec":"unknown","ttftMs":"unknown","completeness":"partial","missing":["tokens"]}
```

**Case C — empty turn** (no first PreInvocation or no terminal Stop — session crash; still recorded for reconciliation):

```json
{"schemaVersion":1,"conversationId":"c-7f3a","turnIndex":4,"timestamp":"2026-11-16T09:40:12Z","modelName":"gemini-3.6-flash-medium","turnLatencyMs":null,"invocationCount":0,"invocationDurationsMs":[],"activeTimeMs":0,"outputTokens":null,"inputTokens":null,"throughputTokensPerSec":null,"ttftMs":"unknown","completeness":"empty","missing":["stop"]}
```

Note the three distinct sentinel values, deliberately non-mixed:
- `null` — should exist but wasn't captured (采集失败)
- `"unknown"` — uncomputable in this architecture (TTFT always; tokens when sidecar missing)
- numeric — real value

`throughputTokensPerSec` = `outputTokens / (activeTimeMs/1000)` = `412 / 4.82` ≈ `85.5`.

---

## 2. Derived session summary (not stored per-line; computed on read)

Across all turns of a conversation, from the per-turn values above:

```json
{"conversationId":"c-7f3a","turnCount":3,"turnLatency":{"p50Ms":5210,"p95Ms":7240,"sumMs":12450},"throughput":{"totalOutputTokens":412,"totalActiveMs":4820,"tokensPerSec":85.5},"completeness":"partial"}
```

Per T5: latency aggregated as p50/p95 + sum; throughput as **total tokens ÷ total active time** (ratio of sums, never mean of per-turn rates).

---

## 3. One-line terminal summary (printed at terminal Stop hook)

Compact (recommended):

```
agy c-7f3a turn#2  7.24s  p50 5.21s  out 412 tok  85.5 tok/s  in 1.9k  [full]
```

Partial case:

```
agy c-7f3a turn#3  5.21s  p50 5.21s  out —  — tok/s  in —  [partial: tokens]
```

Fields shown: `conversationId` (short) · `turnIndex` · `turnLatencyMs/1000` · session `p50` · `outputTokens` · `throughputTokensPerSec` · `inputTokens` · `completeness` (+ `missing` reason when partial). `ttftMs` is intentionally omitted (always unknown).

---

## 4. File path & rotation — to decide (§Q2)

Candidate A (recommended): one file per conversation, `hook-metrics/<conversationId>.jsonl`, beside the ADR-0001 sidecar under `~/.gemini/antigravity-cli/`. No rotation needed (bounded by conversation length). Natural isolation for concurrent sessions.

Candidate B: single global `hook-metrics/metrics.jsonl` appended by all sessions (conversationId in each line) — simpler path, but concurrent-write contention and harder to hand off one conversation.

Candidate C: inside each workspace `.agy-metrics/` — colocated with code but pollutes repos and splits a conversation that spans workspaces.

---

## 5. Output channel — to decide (§Q4, T1 constraint)

T1 fact: hook stdout is a strict JSON contract; **stderr safety is undocumented / unverified**. So the one-line summary cannot assume stderr is safe.

Candidate A (recommended): Stop hook writes the summary to a **dedicated sidecar file** (`hook-metrics/<conversationId>.summary`), and the **statusline command displays it** — statusline stdout is a documented display channel (the same channel ADR-0001 already uses for tokens). Verified-safe.

Candidate B: print to **stderr** from the Stop hook — simplest, but relies on the unverified assumption that stderr is ignored/forwarded harmlessly; must be empirically validated before shipping.

Candidate C: both — sidecar+statusline as the reliable path, stderr as best-effort bonus.
