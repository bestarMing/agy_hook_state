# agy hook & telemetry: fact check

Research ticket: [#2 确认 agy hook 与遥测数据的精确事实](https://github.com/bestarMing/agy_hook_state/issues/2).
Question source: the ticket body (Chinese) reproduced in the "Questions" sections below.

## Method and confidence labels

Investigated against **primary sources first**: the official Google Antigravity documentation (`antigravity.google/docs`), the first-party CLI repository (`google-antigravity/antigravity-cli`, its README / `CHANGELOG.md` / `examples/statusline`), and only then third-party write-ups. Claims are labelled:

- **[official docs]** — stated on `antigravity.google/docs`. Strongest.
- **[first-party source]** — stated in the first-party `google-antigravity/antigravity-cli` repo (CHANGELOG / example scripts). Strong, but may be newer than the docs page.
- **[third-party only / unverified]** — found only in third-party sources; **not confirmed by any official or first-party source**. Treat as a hypothesis to validate empirically.
- **[not documented]** — explicitly searched for and **absent** from the primary sources. Means "cannot be confirmed", not "proven false".

A key overall result: the official docs document the **hook** channel and the **statusline** channel well, but document **almost nothing about `transcript.jsonl`'s internal structure or any on-disk database**. Most "known" transcript details are third-party reverse-engineering and should be downgraded.

---

## Q1. Does the hook JSON payload really contain no timestamps, durations or token counts? List actual fields per event.

**Answer: Confirmed for the documented payload — no timestamp, duration, or token-count field exists in any hook event's stdin or stdout.** **[official docs]** + **[first-party source]**

Source: <https://antigravity.google/docs/hooks/> ; additional fields from <https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md>.

Common stdin fields, present for **every** event **[official docs]** (`antigravity.google/docs/hooks/`):

| Field | Type | Meaning |
|---|---|---|
| `conversationId` | string | UUID of the active conversation |
| `workspacePaths` | string[] | absolute mounted workspace paths |
| `transcriptPath` | string | absolute path to persistent `transcript.jsonl` |
| `artifactDirectoryPath` | string | absolute path to conversation artifacts/screenshots |
| `modelName` | string | e.g. `gemini-3.6-flash-medium` |
| `lastUserInput` | string | most recent user prompt |

Per-event fields **[official docs]** (same URL):

| Event | Event-specific stdin fields | stdout fields |
|---|---|---|
| `SessionStart` | — (common only) | `injectSteps` (optional) |
| `PreToolUse` | `toolCall` (`name`, `args`), `stepIdx` (0-based) | `decision` (required; `allow`/`auto_approve`/`deny`/`ask`/`force_ask`/`deny_unless_prior_grant`), `reason`, `overwrite`, `permissionOverrides` |
| `PostToolUse` | `toolCall` (`name`, `args`), `stepIdx`, `error` (optional) | `{}` (empty JSON object) |
| `PreInvocation` | `invocationNum` (0-based), `initialNumSteps` | `injectSteps`, `terminationBehavior` (`terminate` / `""`) |
| `PostInvocation` | `invocationNum`, `initialNumSteps` | `injectSteps`, `terminationBehavior` (`force_continue`/`terminate`/`""`) |
| `Stop` | `executionNum`, `terminationReason` (e.g. `model_stop`, `max_steps_exceeded`, `error`), `error` (optional), `fullyIdle` (required bool) | `decision` (required; `continue` prevents stop), `reason` |

Additional fields added after that docs page was written, from the **first-party CHANGELOG** **[first-party source]** (`https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md`):

- `hookEventName`, `cwd`, and `toolCall.id` were added to hook stdin "so a single hook command can handle several events, knows the agent's working directory, and can match a `PostToolUse` call to its `PreToolUse` call."
- `continuation_active` was added to `Stop` stdin: `true` while the agent is already working on a continuation an earlier Stop hook requested.
- Note a docs inconsistency: the `/docs/hooks/` page marks `Stop.decision` as required, while the first-party `/docs/build-plugins/` page says returning `{}` allows the stop.

**No** field named like `timestamp`, `created_at`, `duration`, `tokens`, `inputTokens`, `outputTokens`, `totalTokens`, or similar appears in either source. Fields that look numeric (`stepIdx`, `invocationNum`, `initialNumSteps`, `executionNum`) are counters/indices, not time or tokens.

Corroboration (third-party, not needed for the conclusion): SigNoz's monitoring guide states "Antigravity sends no token counts, and the hook spans have zero duration" and "PostToolUse carries no timing ... these spans are point-in-time markers" — <https://signoz.io/docs/antigravity-cli-monitoring>.

---

## Q2. Structure of `transcript.jsonl` lines at `transcriptPath`; `created_at` format/precision/timezone; per-step completion timestamp?

### What is actually documented (primary sources)

- `transcriptPath` is a common hook stdin field: "The absolute path to the persistent `transcript.jsonl` conversation logs." **[official docs]** <https://antigravity.google/docs/hooks/>
- Location pattern **[official docs]** (same URL): `<app_data_dir>/brain/<conversationId>/.system_generated/logs/transcript.jsonl`, with `<app_data_dir>` = `~/.gemini/antigravity-cli` for CLI (`~/.gemini/antigravity` App, `~/.gemini/antigravity-ide` IDE).
- **Nothing else.** The official docs' Settings / CLI-conversations / Sidecars pages were checked and contain **no** line schema, no `created_at`, no token fields, no database description. **[not documented]**
  - <https://antigravity.google/docs/settings/>
  - <https://antigravity.google/docs/cli/conversations/>
  - <https://antigravity.google/docs/sidecars/> (sidecars are a different feature; no transcript/token content)

### What third-party sources claim — **[third-party only / unverified]**

These agree with each other but are **reverse-engineering, not official**:

- One JSON object per **step** per line. Top-level keys: `step_index`, `source`, `type`, `status`, `created_at`, `content`, optional `tool_calls` (`[{name, args}]`), optional `truncated_fields` (only in `transcript.jsonl`).
  - <https://github.com/physercoe/termipod/blob/main/docs/decisions/035-antigravity-engine-m4-locallogtail.md>
  - <https://github.com/jxoesneon/Ciel/blob/main/skills/ciel/references/antigravity_conversations.md>
  - <https://pkg.go.dev/github.com/wilbeibi/catchup@v0.2.0/internal/agy>
- `source` values include `USER_EXPLICIT`, `MODEL`, `SYSTEM`, `SYSTEM_SDK`; `type` values include `USER_INPUT`, `PLANNER_RESPONSE`, `GENERIC`, `EPHEMERAL_MESSAGE`, `SYSTEM_MESSAGE`, `RUN_COMMAND`, `CODE_ACTION`, `VIEW_FILE`, `LIST_DIRECTORY`, `SEARCH_WEB`, `INVOKE_SUBAGENT`, `CONVERSATION_HISTORY`, `CHECKPOINT`. (Sources as above.)
- `created_at` is **RFC 3339**; the one published example is `2026-07-17T09:00:00Z` — whole-second precision, `Z` (UTC). **Precision and timezone rules beyond this single example are unverified.** <https://vshulcz.github.io/deja-vu/registry/antigravity.html>
- **No structured completion timestamp** on a step. The only top-level time field is `created_at`; step completion is represented by `status` flipping `RUNNING` → `DONE` **in place** (the file is a rewritten snapshot, not an append-only log; final file has one line per unique `step_index`). <https://github.com/physercoe/termipod/blob/main/docs/decisions/035-antigravity-engine-m4-locallogtail.md>
  - Caveat: a third-party reader mentions tool-step **content bodies** carrying a human-readable `Created At:` / `Completed At:` **text header** that is stripped from retained output. This is text inside `content`, not a JSON field, and its format/precision is undocumented. <https://vshulcz.github.io/deja-vu/registry/antigravity.html>
- `transcript_full.jsonl` is a sibling with the same events but untruncated `content`. (termipod ADR, Ciel reference — both above.)
- No token-count field appears in the claimed transcript schema. (termipod ADR, Ciel reference — both above.)

**Bottom line for ticket #2:** the `created_at`-based latency approach rests entirely on third-party reverse-engineering. The field name and path are official; its format, precision, timezone, and the absence of a completion timestamp are **unverified** and must be marked as assumptions in the spec (as issue #1's "Not yet specified" already anticipates).

---

## Q3. Is `context_window{total_input_tokens, total_output_tokens, ...}` cumulative or per-turn delta? Is statusline a separate channel from hooks, and can hooks read it?

Source: <https://antigravity.google/docs/cli/statusline/>.

### Fields **[official docs]**

Verbatim: "Contains token usage details: `total_input_tokens`, `total_output_tokens`, `context_window_size` (`0` if unknown), `used_percentage`, `remaining_percentage`, and `current_usage` (`null` before the first model response)."

The payload example additionally shows `current_usage.input_tokens`, `current_usage.output_tokens`, `current_usage.cache_creation_input_tokens`, `current_usage.cache_read_input_tokens`.

### Cumulative vs delta

- The words **"cumulative"**, **"delta"**, **"per turn"**, **"per-turn"**, and **"since session start" do not appear on the page**. **[not documented]**
- Best-supported interpretation: `total_input_tokens` / `total_output_tokens` are **cumulative-to-now totals** (the `total_` naming, the separate `current_usage` object, and `used_percentage` derived from `context_window_size` all point this way). `current_usage` looks like the latest model call's usage. **This is inference, not an official statement.** Confidence: medium-high for "cumulative", low for the precise semantics of `current_usage`.

### Separate channel, and hook readability

- **Separate channel: confirmed [official docs].** `statusLine` is configured in `~/.gemini/antigravity-cli/settings.json` (not in `hooks.json`), runs its own command, and has its own snake_case payload (`conversation_id`, `transcript_path`, `context_window`, …) versus hooks' camelCase (`conversationId`, `transcriptPath`, …). Verbatim: "Whenever the agent state changes, the CLI runs your command with `sh -c` (`cmd /c` on Windows), pipes the session state as JSON to its `stdin`, and shows what the command prints to `stdout` in the status line." Throttled to at most once per 300 ms; runs over 5 s are stopped; 30 consecutive failures disable the status line for the session.
- First-party CHANGELOG corroborates separation: headless `-p` runs "no longer start your custom status line and window title commands". **[first-party source]**
- **Can a hook read the statusline payload? [not documented].** No documented API, event, or shared file connects the two channels. A hook could only obtain these numbers if the user's own statusline command first persisted them to a sidecar file the hook then reads — that is a user-built bridge, not a product feature, and is unverified.

---

## Q4. Is hook stdout a strict JSON contract? Can you print to stderr? `timeout` default and behavior?

Source: <https://antigravity.google/docs/hooks/> , <https://antigravity.google/docs/build-plugins/#lifecycle-hooks> , first-party <https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md>.

### stdout contract **[official docs]**

- "Hooks receive input through **stdin** as JSON and return output through **stdout** as JSON. Field names use camelCase."
- First-party docs' build-plugins page is stricter: command hooks "must exit with code **`0`** and write a JSON response object to `stdout` ... Any non-zero exit code is logged as a hook execution error and ignored (failing open)."
- So stdout is the designated structured channel and must contain the JSON response; non-zero exits fail open.

### stderr **[not documented]**

- The word **`stderr` is entirely absent** from the official hooks documentation (and from the hook sections of the first-party docs/repo). There is **no official statement** that stderr output is ignored, forwarded, logged, or fatal.
- Therefore "print diagnostics to stderr without breaking the contract" is **unverified**. It is a reasonable engineering hypothesis (the contract constrains stdout only), but the spec should label it as such and validate it empirically before relying on it for the terminal one-line summary. The map issue #1 already carries this as a constraint ("需走 stderr 或旁路") — downgrade its confidence from confirmed to hypothesis.

### `timeout` default and behavior

- Default **`30` seconds**, field type integer, "Timeout in seconds". **[official docs]** <https://antigravity.google/docs/hooks/>
- One first-party exception: hooks converted by `agy plugin import` get a **60-second** default timeout. **[first-party source]** (CHANGELOG).
- Behavior on timeout / invalid JSON **[first-party source]** (CHANGELOG): a `PostToolUse` hook that "fails to run, for example because its command is missing, exits with an error, **times out, or prints invalid JSON**" no longer marks the tool call failed — "the failure is now logged and the tool keeps its result" (fail-open). Exact kill mechanics (SIGKILL vs terminate, grace period, stderr on timeout) are **[not documented]**.
- Do not confuse with the statusline's separate 5-second limit (Q3) or headless `-p` timeouts.

---

## Q5. Non-hook token/timestamp sources readable by the same process?

### Officially documented sources

- **Statusline JSON payload** contains token usage (`context_window.*`) and estimated spend (`cost.total_usd`, `cost.subagent_usd`, `cost.estimated`) **[official docs]** <https://antigravity.google/docs/cli/statusline/>. But it is a separate channel with no hook-facing API (Q3) — not directly readable "by the same process" as a hook without a user-built bridge.
- **Plugin-hook environment variables** `PLUGIN_ROOT` and `PLUGIN_DATA` (persistent data folder for state between runs) **[first-party source]** (CHANGELOG). Neither carries tokens/timestamps. No official list of hook env vars with token/time data exists. **[not documented]**
- **Sidecar env var** `ANTIGRAVITY_EXECUTABLE_DATA_DIR` points at a sidecar's `data/` dir **[official docs]** <https://antigravity.google/docs/sidecars/>. Sidecars are an App-only, separate feature; no documented hook-token linkage.
- **On-disk prompt history** exists (`historySize`, default `2000`, entries "kept on disk") **[official docs]** <https://antigravity.google/docs/settings/>, but no path/schema/fields are documented.
- **Telemetry** is account-level, always off for business accounts **[official docs]** <https://antigravity.google/docs/settings/>; not a local token source.

### Third-party only — **[third-party only / unverified]**

Under `~/.gemini/antigravity-cli/` third-party observers report:

- `conversations/<id>.db` — **SQLite conversation store, described as authoritative state**, paired with `conversations/<id>.pb` protobuf resume state; `conversation_summaries.db` an index. **No schema is published**, so whether it contains token counts or timestamps is unverified. <https://github.com/jxoesneon/Ciel/blob/main/skills/ciel/references/antigravity_conversations.md> , <https://pkg.go.dev/github.com/wilbeibi/catchup@v0.2.0/internal/agy>
- `brain/<id>/.system_generated/logs/transcript.jsonl` / `transcript_full.jsonl` — step stream (see Q2), no token fields; plus `chunks/`, `tasks/task-*.log`, `messages/*.json`, `annotations/.pbtxt`, `presence/.lock`. (Ciel reference.)
- `history.jsonl` — one line per user action: `{display, timestamp, workspace, conversationId}`; timestamp format unspecified. (Ciel reference; termipod ADR.)
- `cli.log`, `cache/last_conversations.json`, `settings.json`, `mcp_config.json`. (termipod ADR.)
- Environment caveat for observability tooling: "An interactive agy session inherits whatever shell launched it, so hooks rarely see the `OTEL_EXPORTER_OTLP_*` variables you export in your terminal" — **third-party** <https://signoz.io/docs/antigravity-cli-monitoring>. This suggests hooks inherit the `agy` process environment, but no official env-var inventory exists.

Because a hook is just a local process, it *could* open any of these files if the paths are known; that is a filesystem capability, not a documented product contract, and the contents/schemas remain unverified.

---

## Confidence summary

| Question | Confirmed by official/first-party | Still unverified |
|---|---|---|
| 1. No timestamps/durations/tokens in hook payload; per-event fields | Yes (plus extra fields from CHANGELOG) | Exact Stop-`decision` contract differs between two official pages |
| 2. transcript.jsonl structure | Only `transcriptPath` existence + path pattern | Line schema, `created_at` format/precision/timezone, no-completion-timestamp claim, `RUNNING`→`DONE` rewrite, `transcript_full.jsonl` — all third-party |
| 3. context_window cumulative vs delta | Fields and separate-channel status confirmed | "Cumulative" is inference; docs never say so. No hook→statusline read path |
| 4. stdout JSON contract, timeout default 30s, fail-open on timeout/invalid JSON | Yes (stdout/JSON contract + CHANGELOG failure semantics) | **stderr safety is completely undocumented**; timeout kill details undocumented |
| 5. Other token/timestamp sources | Statusline payload & plugin env vars exist; on-disk history exists | `conversations/<id>.db` schema/contents, `history.jsonl` timestamp format, any usable env-var token source |

## Sources

Official docs:
- <https://antigravity.google/docs/hooks/>
- <https://antigravity.google/docs/cli/statusline/>
- <https://antigravity.google/docs/build-plugins/>
- <https://antigravity.google/docs/cli/reference/>
- <https://antigravity.google/docs/cli/conversations/>
- <https://antigravity.google/docs/settings/>
- <https://antigravity.google/docs/sidecars/>

First-party repo:
- <https://github.com/google-antigravity/antigravity-cli> (README, `CHANGELOG.md`, `examples/statusline/statusline.sh`)

Third-party (lower confidence, listed for traceability):
- <https://github.com/physercoe/termipod/blob/main/docs/decisions/035-antigravity-engine-m4-locallogtail.md>
- <https://github.com/jxoesneon/Ciel/blob/main/skills/ciel/references/antigravity_conversations.md>
- <https://pkg.go.dev/github.com/wilbeibi/catchup@v0.2.0/internal/agy>
- <https://vshulcz.github.io/deja-vu/registry/antigravity.html>
- <https://signoz.io/docs/antigravity-cli-monitoring>
