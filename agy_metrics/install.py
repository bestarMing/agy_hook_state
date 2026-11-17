from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

HOOK_NAME = "agy-metrics"
HOOK_EVENTS = ("SessionStart", "PreInvocation", "PostInvocation", "Stop")
LAUNCHER_NAME = "agy_metrics_launcher.py"


def _quote_command(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return data


def _backup(path: Path) -> None:
    if path.exists():
        path.replace(path.with_suffix(path.suffix + ".bak"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def merge_hooks(existing: dict, command: str, timeout: int) -> dict:
    result = copy.deepcopy(existing)
    bundle = result.setdefault(HOOK_NAME, {})
    if not isinstance(bundle, dict):
        bundle = result[HOOK_NAME] = {}
    new_hook = {"type": "command", "command": command, "timeout": timeout}
    for event in HOOK_EVENTS:
        handlers = bundle.setdefault(event, [])
        if not isinstance(handlers, list):
            handlers = bundle[event] = []
        if any(
            isinstance(h, dict) and h.get("command") == command
            for h in handlers
        ):
            continue
        handlers.append(dict(new_hook))

    # Clean up any legacy un-namespaced hooks added by older installer versions
    for event in HOOK_EVENTS:
        if event in result and isinstance(result[event], list):
            cleaned = []
            for item in result[event]:
                if isinstance(item, dict) and "hooks" in item:
                    sub = [
                        h for h in item.get("hooks", [])
                        if not (isinstance(h, dict) and (h.get("command") == command or "agy_metrics_launcher.py" in h.get("command", "")))
                    ]
                    if sub:
                        item_copy = dict(item)
                        item_copy["hooks"] = sub
                        cleaned.append(item_copy)
                elif isinstance(item, dict):
                    if not (item.get("command") == command or "agy_metrics_launcher.py" in item.get("command", "")):
                        cleaned.append(item)
            if cleaned:
                result[event] = cleaned
            else:
                del result[event]

    return result


def merge_settings(existing: dict, command: str) -> dict:
    result = copy.deepcopy(existing)
    result["statusLine"] = {"type": "command", "command": command}
    return result


def _launcher_source(repo_root: Path) -> str:
    return (
        "from __future__ import annotations\n"
        f"import sys\nsys.path.insert(0, {str(repo_root)!r})\n"
        "from agy_metrics.hook_command import main as hook_main\n"
        "from agy_metrics.statusline import main as statusline_main\n"
        "if __name__ == '__main__':\n"
        "    mode = sys.argv[1] if len(sys.argv) > 1 else 'hook'\n"
        "    if mode == 'statusline':\n"
        "        raise SystemExit(statusline_main())\n"
        "    if mode == 'hook':\n"
        "        raise SystemExit(hook_main())\n"
        "    raise SystemExit(2)\n"
    )


def install(
    home: Path,
    repo_root: Path | None = None,
    python: str | None = None,
) -> dict:
    repo_root = (repo_root or Path(__file__).resolve().parent.parent).resolve()
    python = python or sys.executable

    hooks_path = home / ".gemini" / "config" / "hooks.json"
    settings_path = home / ".gemini" / "antigravity-cli" / "settings.json"
    launcher_path = home / ".gemini" / "antigravity-cli" / LAUNCHER_NAME

    hook_command = _quote_command([python, str(launcher_path), "hook"])
    statusline_command = _quote_command([python, str(launcher_path), "statusline"])

    # Read everything before writing anything, so a bad config aborts cleanly.
    existing_hooks = _read_json(hooks_path)
    existing_settings = _read_json(settings_path)
    merged_hooks = merge_hooks(existing_hooks, hook_command, 30)
    merged_settings = merge_settings(existing_settings, statusline_command)

    _backup(hooks_path)
    _backup(settings_path)
    _write_json(hooks_path, merged_hooks)
    _write_json(settings_path, merged_settings)

    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_text(_launcher_source(repo_root), encoding="utf-8")

    return {
        "launcher": str(launcher_path),
        "hooks": str(hooks_path),
        "settings": str(settings_path),
        "hook_command": hook_command,
        "statusline_command": statusline_command,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-click setup of agy latency/throughput hooks"
    )
    parser.add_argument(
        "--home", type=Path, default=Path.home(),
        help="user home to write config under (default: current user home)",
    )
    args = parser.parse_args(argv)
    try:
        report = install(args.home)
    except ValueError as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1
    print(f"launcher:  {report['launcher']}")
    print(f"hooks:     {report['hooks']}")
    print(f"statusLine:{report['settings']}")
    print("Done. Restart agy to pick up the hooks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
