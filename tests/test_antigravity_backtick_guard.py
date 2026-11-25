# -*- coding: utf-8 -*-
"""antigravity_backtick_guard.py 어댑터 및 Antigravity hooks.json 배선 시험."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
ADAPTER = SCRIPTS / "antigravity_backtick_guard.py"
PS_GUARD = SCRIPTS / "ps_publish_guard.py"
BASH_GUARD = SCRIPTS / "bash_quote_guard.py"
BT = "`"

sys.path.insert(0, str(SCRIPTS))
import antigravity_backtick_guard as ag  # noqa: E402


def _make_payload(command: str, *, tool: str = "run_command", arg_key: str = "CommandLine", extra_args: dict | None = None) -> dict:
    args = {arg_key: command}
    if extra_args:
        args.update(extra_args)
    return {
        "hookEventName": "PreToolUse",
        "stepIdx": 1,
        "conversationId": "test-conv",
        "workspacePaths": ["example-project"],
        "toolCall": {
            "id": "toolu_test",
            "name": tool,
            "args": args,
        },
    }


def _make_manage_task_payload(action: str, input_text: str | None = None) -> dict:
    args: dict = {"Action": action, "TaskId": "conv/task-1"}
    if input_text is not None:
        args["Input"] = input_text
    return {
        "hookEventName": "PreToolUse",
        "stepIdx": 2,
        "conversationId": "test-conv",
        "workspacePaths": ["example-project"],
        "toolCall": {
            "id": "toolu_mt",
            "name": "manage_task",
            "args": args,
        },
    }


def _run_adapter(stdin_bytes: bytes, *extra_args: str) -> tuple[int, str, dict | None]:
    proc = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-B", str(ADAPTER), *extra_args],
        input=stdin_bytes,
        capture_output=True,
        timeout=30,
    )
    out = proc.stdout.decode("utf-8", "replace")
    parsed = json.loads(out) if out.strip() else None
    return proc.returncode, out, parsed


def _run_raw_guard(guard_path: Path, command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-B", str(guard_path), "--raw", "--block-code=42"],
        input=command.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )


class AdapterDecisionTests(unittest.TestCase):
    def test_powershell_probe_blocked_with_exact_ps_guard_reason(self):
        cmd = 'if ($false) { gh release create v0.0.0-probe --notes "probe ' + BT + 'x' + BT + ' text" }'
        raw = _run_raw_guard(PS_GUARD, cmd)
        self.assertEqual(raw.returncode, 42)
        rc, _, res = _run_adapter(json.dumps(_make_payload(cmd)).encode("utf-8"), "--shell=powershell")
        self.assertEqual(rc, 0)
        self.assertIsNotNone(res)
        self.assertEqual(res["decision"], "deny")
        self.assertEqual(res["reason"], raw.stderr.decode("utf-8", "replace").strip())
        self.assertIn("[backtick-check-hook]", res["reason"])

    def test_release_here_string_notes_file_pattern_is_blocked(self):
        cmd = (
            '$body = @"\n'
            'Release notes with \\' + BT + 'widget\\' + BT + '.\n'
            '"@\n'
            '[IO.File]::WriteAllText("notes.md", $body)\n'
            'gh release create v1.2.3 --notes-file notes.md'
        )
        rc, _, res = _run_adapter(json.dumps(_make_payload(cmd)).encode("utf-8"), "--shell=powershell")
        self.assertEqual(rc, 0)
        self.assertIsNotNone(res)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("[backtick-check-hook]", res["reason"])

    def test_powershell_safe_commands_emit_empty_stdout_no_decision(self):
        """막지 않을 때는 allow나 {}가 아니라 빈 표준 출력(훅 의견 없음)으로 기본 정책에 위임한다."""
        safe_cmds = [
            'Write-Output "a' + BT + 'tb"',
            "echo plain",
            "gh release create v0.0.0-probe --notes-file notes.md",
            "gh release create v0.0.0-probe --notes 'probe " + BT + "x" + BT + " text'",
            "git commit -F msg.txt",
        ]
        for cmd in safe_cmds:
            with self.subTest(cmd=cmd):
                rc, raw_out, res = _run_adapter(json.dumps(_make_payload(cmd)).encode("utf-8"), "--shell=powershell")
                self.assertEqual(rc, 0)
                self.assertEqual(raw_out, "")
                self.assertIsNone(res)

    def test_manage_task_send_input_blocks_publish_backtick_and_allows_safe_actions(self):
        bad = 'if ($false) { gh release create v0.0.0-probe --notes "probe ' + BT + 'x' + BT + ' text" }\n'
        rc, _, res = _run_adapter(json.dumps(_make_manage_task_payload("send_input", bad)).encode("utf-8"), "--shell=powershell")
        self.assertEqual(rc, 0)
        self.assertIsNotNone(res)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("[backtick-check-hook]", res["reason"])

        safe_payloads = [
            _make_manage_task_payload("send_input", "y\n"),
            _make_manage_task_payload("send_input", 'Write-Output "a' + BT + 'tb"\n'),
            _make_manage_task_payload("status", bad),
            _make_manage_task_payload("list"),
            _make_manage_task_payload("kill"),
        ]
        for p in safe_payloads:
            with self.subTest(action=p["toolCall"]["args"].get("Action")):
                rc, raw_out, res = _run_adapter(json.dumps(p).encode("utf-8"), "--shell=powershell")
                self.assertEqual(rc, 0)
                self.assertEqual(raw_out, "")
                self.assertIsNone(res)

    def test_bash_probe_blocked_and_safe_forms_pass(self):
        bad = 'if false; then echo "probe ' + BT + 'whoami' + BT + ' text"; fi'
        raw = _run_raw_guard(BASH_GUARD, bad)
        self.assertEqual(raw.returncode, 42)
        rc, _, res = _run_adapter(json.dumps(_make_payload(bad)).encode("utf-8"), "--shell=bash")
        self.assertEqual(rc, 0)
        self.assertIsNotNone(res)
        self.assertEqual(res["decision"], "deny")
        self.assertEqual(res["reason"], raw.stderr.decode("utf-8", "replace").strip())
        self.assertIn("[backtick-check-hook]", res["reason"])

        for good in ("echo 'probe " + BT + "whoami" + BT + " text'", "echo plain"):
            with self.subTest(cmd=good):
                rc, raw_out, res = _run_adapter(json.dumps(_make_payload(good)).encode("utf-8"), "--shell=bash")
                self.assertEqual(rc, 0)
                self.assertEqual(raw_out, "")
                self.assertIsNone(res)

    def test_windows_ignores_bash_hint_in_tool_args(self):
        """Windows에서는 도구 인자의 bash 힌트를 무시하고 PowerShell 검사기를 써야 한다."""
        self.assertEqual(ag.select_shell({}, platform="win32"), "powershell")
        self.assertEqual(ag.select_shell({"Shell": "bash"}, platform="win32"), "powershell")
        self.assertEqual(ag.select_shell({"shell": "C:/Program Files/Git/bin/bash.exe"}, platform="win32"), "powershell")
        self.assertEqual(ag.select_shell({}, platform="linux"), "bash")
        self.assertEqual(ag.select_shell({"Shell": "pwsh.exe"}, platform="linux"), "powershell")

        cmd = 'if ($false) { gh release create v0.0.0-probe --notes "probe ' + BT + 'x' + BT + ' text" }'
        for hint in ({"Shell": "bash"}, {"shell": "bash"}, {"Shell": "C:/Program Files/Git/bin/bash.exe"}):
            with self.subTest(hint=hint):
                payload = _make_payload(cmd, extra_args=hint)
                res = ag.evaluate_payload(payload, platform="win32")
                self.assertIsNotNone(res)
                self.assertEqual(res["decision"], "deny")
                self.assertIn("[backtick-check-hook]", res["reason"])

    @unittest.skipUnless(sys.platform == "win32", "Windows subprocess check for ignored bash hint")
    def test_windows_subprocess_ignores_bash_hint_without_override(self):
        cmd = 'if ($false) { gh release create v0.0.0-probe --notes "probe ' + BT + 'x' + BT + ' text" }'
        payload = _make_payload(cmd, extra_args={"Shell": "bash"})
        rc, _, res = _run_adapter(json.dumps(payload).encode("utf-8"))
        self.assertEqual(rc, 0)
        self.assertIsNotNone(res)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("[backtick-check-hook]", res["reason"])

    def test_other_tools_and_malformed_inputs_fail_open_with_empty_stdout(self):
        bad_cmd = 'gh release create v1 --notes "use ' + BT + 'x' + BT + '"'
        cases = [
            json.dumps(_make_payload(bad_cmd, tool="write_file")).encode("utf-8"),
            json.dumps(_make_payload(bad_cmd, tool="read_file")).encode("utf-8"),
            b"",
            b"{not valid json",
            json.dumps({"toolCall": {"name": "run_command", "args": {}}}).encode("utf-8"),
            json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": 123}}}).encode("utf-8"),
        ]
        for raw_in in cases:
            with self.subTest(raw_in=raw_in[:40]):
                rc, raw_out, res = _run_adapter(raw_in, "--shell=powershell")
                self.assertEqual(rc, 0)
                self.assertEqual(raw_out, "")
                self.assertIsNone(res)

    def test_missing_or_crashing_guard_script_fails_open(self):
        cmd = 'gh release create v1 --notes "use ' + BT + 'x' + BT + '"'
        payload = _make_payload(cmd)
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(ag.evaluate_payload(payload, platform="win32", scripts_dir=td))
            fake = Path(td) / "ps_publish_guard.py"
            fake.write_text("import sys; sys.exit(2)\n", encoding="utf-8")
            self.assertIsNone(ag.evaluate_payload(payload, platform="win32", scripts_dir=td))
            fake.write_text("import sys; sys.exit(1)\n", encoding="utf-8")
            self.assertIsNone(ag.evaluate_payload(payload, platform="win32", scripts_dir=td))

    def test_lowercase_command_key_fallback_supported(self):
        cmd = 'gh release create v1 --notes "use ' + BT + 'x' + BT + '"'
        rc, _, res = _run_adapter(
            json.dumps(_make_payload(cmd, arg_key="commandLine")).encode("utf-8"),
            "--shell=powershell",
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(res)
        self.assertEqual(res["decision"], "deny")

if __name__ == "__main__":
    unittest.main()
