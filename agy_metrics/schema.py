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
    toolTimeMs: int | None | str
    outputTokens: int | None | str
    inputTokens: int | None | str
    throughputTokensPerSec: float | None | str
    ttftMs: str
    thinkingDurationMs: str
    completeness: Completeness
    missing: list[str]
    crossCheck: dict[str, Any]
