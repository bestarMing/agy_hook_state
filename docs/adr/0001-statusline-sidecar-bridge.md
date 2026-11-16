---
status: accepted
---

# Accept a user-built statusline→sidecar bridge for token counts

`agy` hook payloads carry no timestamps or token counts (confirmed against official docs and first-party sources), but the spec must report output throughput (`output tokens / generation window`). The only officially documented token source is the **statusline** channel, which is a separate mechanism (own command in `settings.json`, snake_case payload) with no hook-facing API. We decided to accept a **user-built bridge**: the statusline command writes a token snapshot to a per-conversation sidecar file, which the Stop hook reads at aggregation time. The alternative of switching to `stream-json` output was ruled out of scope during charting, and abandoning token metrics would defeat the "throughput" goal. This bridge is a deliberate, non-obvious dependency on a non-official component and is recorded as a **to-be-validated assumption** in the spec — a future reader should not "simplify" it away, because without it no token data reaches the hook.
