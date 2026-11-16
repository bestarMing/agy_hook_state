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
