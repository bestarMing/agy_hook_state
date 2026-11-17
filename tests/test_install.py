import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agy_metrics import install as installer


HOOK_EVENTS = ("SessionStart", "PreInvocation", "PostInvocation", "Stop")


class TestMergeConfig(unittest.TestCase):
    def test_merge_hooks_adds_four_events_idempotently(self):
        merged = installer.merge_hooks({}, "CMD", 30)
        for event in HOOK_EVENTS:
            hooks = merged[event][0]["hooks"]
            self.assertEqual(len(hooks), 1)
            self.assertEqual(hooks[0]["command"], "CMD")
            self.assertEqual(hooks[0]["timeout"], 30)
            self.assertEqual(hooks[0]["type"], "command")

        merged_again = installer.merge_hooks(merged, "CMD", 30)
        for event in HOOK_EVENTS:
            self.assertEqual(len(merged_again[event][0]["hooks"]), 1)

    def test_merge_hooks_preserves_unrelated_events_and_hooks(self):
        existing = {
            "PreToolUse": [{"hooks": [{"type": "command", "command": "mine"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "keep-me"}]}],
        }
        merged = installer.merge_hooks(existing, "CMD", 30)
        self.assertEqual(merged["PreToolUse"], existing["PreToolUse"])
        cmds = [h["command"] for h in merged["Stop"][0]["hooks"]]
        self.assertIn("keep-me", cmds)
        self.assertIn("CMD", cmds)

    def test_merge_settings_replaces_statusline_but_preserves_other_keys(self):
        merged = installer.merge_settings(
            {"theme": "dark", "statusLine": {"command": "old"}}, "NEW"
        )
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(merged["statusLine"], {"type": "command", "command": "NEW"})


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.repo = Path(__file__).resolve().parent.parent

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_writes_launcher_and_configs(self):
        report = installer.install(self.home, repo_root=self.repo)

        launcher = Path(report["launcher"])
        self.assertTrue(launcher.exists())
        source = launcher.read_text(encoding="utf-8")
        self.assertIn(str(self.repo).replace("\\", "\\\\"), source)
        self.assertIn("hook", source)
        self.assertIn("statusline", source)

        hooks = json.loads((self.home / ".gemini/config/hooks.json").read_text(encoding="utf-8"))
        for event in HOOK_EVENTS:
            cmd = hooks[event][0]["hooks"][0]["command"]
            self.assertIn("hook", cmd)
            self.assertIn(str(launcher), cmd)

        settings = json.loads(
            (self.home / ".gemini/antigravity-cli/settings.json").read_text(encoding="utf-8")
        )
        self.assertEqual(settings["statusLine"]["type"], "command")
        self.assertIn("statusline", settings["statusLine"]["command"])

    def test_install_creates_backups_and_is_idempotent(self):
        hooks_path = self.home / ".gemini/config/hooks.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(json.dumps({"Custom": []}), encoding="utf-8")

        installer.install(self.home, repo_root=self.repo)
        installer.install(self.home, repo_root=self.repo)

        self.assertTrue(hooks_path.with_suffix(".json.bak").exists())
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertIn("Custom", hooks)
        for event in HOOK_EVENTS:
            self.assertEqual(len(hooks[event][0]["hooks"]), 1)

    def test_install_refuses_to_clobber_invalid_json(self):
        hooks_path = self.home / ".gemini/config/hooks.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text("{ not valid json", encoding="utf-8")

        with self.assertRaises(ValueError):
            installer.install(self.home, repo_root=self.repo)
        self.assertEqual(hooks_path.read_text(encoding="utf-8"), "{ not valid json")


class TestLauncherRunsFromAnyCwd(unittest.TestCase):
    def test_launcher_drives_hook_and_statusline_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            repo = Path(__file__).resolve().parent.parent
            report = installer.install(home, repo_root=repo)
            launcher = report["launcher"]
            env = dict(os.environ, AGY_METRICS_DIR=str(home / "state"))
            unrelated_cwd = home  # not the repo root

            hook_payload = json.dumps({
                "hookEventName": "SessionStart",
                "conversationId": "conv-x",
                "modelName": "m",
            })
            proc = subprocess.run(
                [sys.executable, launcher, "hook"],
                input=hook_payload, text=True, capture_output=True,
                cwd=unrelated_cwd, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), {})

            status_payload = json.dumps({
                "conversation_id": "conv-x",
                "context_window": {"total_output_tokens": 5, "total_input_tokens": 9},
            })
            proc = subprocess.run(
                [sys.executable, launcher, "statusline"],
                input=status_payload, text=True, capture_output=True,
                cwd=unrelated_cwd, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
