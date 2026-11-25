"""Read and execute the declarations written into a temporary home."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from isolated_home import IsolatedHome, MARKER, REPO, declaration, encoded_command
from test_antigravity_backtick_guard import _make_manage_task_payload, _make_payload
from test_bash_quote_guard import BASH, g
from test_codex_ps_publish_hook import PROBE
from test_ps_publish_guard import ALLOW, BLOCK, _cases


BASH_CASE = 'echo "a `date` b"'
START_MATCHER = "startup|resume|clear|compact|fork"


class InstalledClaudeTests(unittest.TestCase):
    def setUp(self):
        self.h = IsolatedHome(self)
        self.settings = self.h.install("claude")
        self.package = self.h.package("claude")

    def pre(self, matcher):
        return declaration(self.settings, "claude", "PreToolUse", matcher)

    def session(self):
        return declaration(self.settings, "claude", "SessionStart", START_MATCHER)

    def assert_pinned_asset(self, line, script):
        if os.name == "nt" and not self.package.as_posix().isascii():
            root = base64.b64encode(self.package.as_posix().encode("utf-8")).decode("ascii")
            self.assertIn(root, line)
            self.assertIn("/" + script, line)
        else:
            self.assertIn((self.package / script).as_posix(), line)

    def bash(self, command, data=b"{}", *, env=None):
        if not BASH:
            self.skipTest("requires Git Bash or Bash")
        return self.h.run([BASH, "--noprofile", "--norc", "-c", command], data, env=env)

    def check_pre(self, matcher, script):
        rule = self.pre(matcher)
        line = rule["command"]
        self.assertEqual(set(rule), {"type", "command", "timeout"})
        self.assertEqual((rule["type"], rule["timeout"]), ("command", 15))
        self.assertTrue(line.startswith("set +e; LC_ALL=C;"))
        self.assertNotIn("\\", line)
        self.assertEqual(line.count("`"), 1)
        self.assertIn("*'`'*|*u0060*)", line)
        self.assert_pinned_asset(line, "scripts/" + script)
        self.assertNotIn("CLAUDE_PROJECT_DIR", line)
        self.assertIn("-I -X utf8 -B", line)
        self.assertIn("--block-code=42", line)

    def test_bash_settings_wire_one_synchronous_guard(self):
        self.check_pre("Bash|Monitor", "bash_quote_guard.py")

    def test_powershell_settings_wire_one_synchronous_guard(self):
        self.check_pre("PowerShell", "ps_publish_guard.py")

    def test_session_declaration_timeout_matcher_and_exit_contract(self):
        rule = self.session()
        self.assertEqual(set(rule), {"type", "command", "timeout"})
        self.assertGreater(rule["timeout"], 16)
        line = rule["command"]
        self.assert_pinned_asset(line, "scripts/bash_quote_guard.py")
        self.assertIn("--self-test", line)
        self.assertIn("10", line)
        self.assertNotIn("CLAUDE_PROJECT_DIR", line)
        self.assertNotIn("`", line)
        self.assertNotIn("\\", line)
        self.assertTrue(line.rstrip().endswith("exit 0"))

    def test_installed_plugin_and_user_bash_events_agree(self):
        doc = json.loads((self.package / "hooks/hooks.json").read_bytes())
        for event, matcher in [("PreToolUse", "Bash|Monitor"), ("SessionStart", START_MATCHER)]:
            self.assertEqual(declaration(doc, "claude", event, matcher),
                             declaration(self.settings, "claude", event, matcher))

    def test_installed_plugin_and_user_powershell_event_agree(self):
        doc = json.loads((self.package / "hooks/hooks.json").read_bytes())
        self.assertEqual(declaration(doc, "claude", "PreToolUse", "PowerShell"), self.pre("PowerShell"))

    def test_configured_bash_hook_real_shell_and_fail_open(self):
        line = self.pre("Bash|Monitor")["command"]
        for tool, command, expected in [
            ("Bash", BASH_CASE, 2), ("Monitor", BASH_CASE, 2), ("Bash", "ls -la", 0),
            ("Bash", "echo 'a `date` b'", 0), ("Bash", 'echo "now: $(date)"', 0),
            ("Write", "`x`", 0),
        ]:
            with self.subTest(tool=tool, command=command):
                proc = self.bash(line, encoded_command(tool, command))
                self.assertEqual(proc.returncode, expected)
                if expected:
                    self.assertIn(MARKER, proc.stderr.decode("utf-8"))
        self.assertEqual(self.bash(line, b"").returncode, 0)
        socket = {"tool_name": "Monitor", "tool_input": {"ws": {"url": "wss://example.invalid"},
                                                          "description": "`d`"}}
        self.assertEqual(self.bash(line, json.dumps(socket).encode()).returncode, 0)
        raw = encoded_command("Bash", BASH_CASE)
        self.assertEqual(self.bash(line, raw.replace(b"`", br"\u0060")).returncode, 2)
        for locale in ["zh_CN.GBK", "zh_TW.Big5", "C", "ko_KR.UTF-8"]:
            with self.subTest(locale=locale):
                self.assertEqual(self.bash(line, encoded_command("Bash", 'echo "각`echo 각`"'),
                                           env=dict(self.h.env, LC_ALL=locale)).returncode, 2)
        env = dict(self.h.env, SHELLOPTS="errexit")
        self.assertEqual(self.bash(line, raw, env=env).returncode, 2)
        self.assertEqual(self.bash(line, encoded_command("Bash", "echo plain"), env=env).returncode, 0)
        (self.package / "scripts/bash_quote_guard.py").unlink()
        self.assertEqual(self.bash(line, raw).returncode, 0)

    def test_configured_powershell_hook_through_git_bash(self):
        line = self.pre("PowerShell")["command"]
        for table, names, expected in [
            (BLOCK, ("dq-notes", "dq-here-string", "invoke-expression"), 2),
            (ALLOW, ("single-quotes", "notes-file", "not-publishing"), 0),
        ]:
            for name in names:
                with self.subTest(case=name):
                    proc = self.bash(line, encoded_command("PowerShell", _cases(table)[name]))
                    self.assertEqual(proc.returncode, expected, proc.stderr)
                    if expected:
                        self.assertIn(MARKER, proc.stderr.decode("utf-8"))
        (self.package / "scripts/ps_publish_guard.py").unlink()
        self.assertEqual(self.bash(line, encoded_command("PowerShell", PROBE)).returncode, 0)

    def test_session_start_runs_plugin_guard_and_ignores_workspace(self):
        decoy = self.h.cwd / ".claude/settings.json"
        decoy.parent.mkdir()
        marker = self.h.cwd / "unexpected"
        decoy.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash|Monitor",
                         "hooks": [{"type": "command", "command": ": > unexpected # bash_quote_guard.py"}]}]}}),
                         encoding="utf-8")
        env = dict(self.h.env, CLAUDE_PROJECT_DIR=str(self.h.cwd), CLAUDE_PLUGIN_ROOT=str(self.h.cwd))
        proc = self.bash(self.session()["command"], env=env)
        self.assertEqual((proc.returncode, proc.stdout), (0, b""), proc.stderr)
        proc = self.h.run([sys.executable, "-I", "-X", "utf8", "-B",
                           str(self.package / "scripts/bash_quote_guard.py"), "--self-test"], env=env)
        self.assertEqual((proc.returncode, proc.stdout), (10, b""), proc.stderr)
        self.assertFalse(marker.exists())

    def test_session_start_warns_when_plugin_declaration_stops_blocking(self):
        path = self.package / "hooks/hooks.json"
        doc = json.loads(path.read_bytes())
        handler = declaration(doc, "claude", "PreToolUse", "Bash|Monitor")
        handler["command"] = "exit 0  # bash_quote_guard.py"
        path.write_text(json.dumps(doc), encoding="utf-8")
        proc = self.bash(self.session()["command"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("WARNING", proc.stdout.decode("utf-8"))
        self.assertIn("did not block", proc.stdout.decode("utf-8"))

    def test_session_start_warns_for_missing_or_stale_guard_and_python(self):
        line = self.session()["command"]
        path = self.package / "scripts/bash_quote_guard.py"
        path.unlink()
        proc = self.bash(line)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("self-test code 2", proc.stdout.decode("utf-8"))
        path.write_text("pass\n", encoding="ascii")
        proc = self.bash(line)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("self-test code 0", proc.stdout.decode("utf-8"))
        resolver = self.package / "hooks/python.sh"
        resolver.write_text('run_python() { nonexistent_python_for_hook_test "$@"; }\n', encoding="ascii")
        proc = self.bash(line)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("self-test code 127", proc.stdout.decode("utf-8"))
        proc = self.bash(self.pre("Bash|Monitor")["command"], encoded_command("Bash", BASH_CASE))
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))

    @unittest.skipUnless(os.name == "nt", "Git Bash is required for Windows tests")
    def test_git_bash_is_available(self):
        self.assertTrue(BASH)

    def test_repository_plugin_runs_from_a_different_directory(self):
        sample = self.h.root / "설치 plugin"
        sample.mkdir()
        shutil.copytree(REPO / "scripts", sample / "scripts")
        shutil.copytree(REPO / "hooks", sample / "hooks")
        doc = json.loads((sample / "hooks/hooks.json").read_bytes())
        env = dict(self.h.env, CLAUDE_PLUGIN_ROOT=sample.as_posix())
        for matcher, tool, data in [("Bash|Monitor", "Bash", BASH_CASE), ("PowerShell", "PowerShell", PROBE)]:
            with self.subTest(tool=tool):
                line = declaration(doc, "claude", "PreToolUse", matcher)["command"]
                self.assertIn('"\u0024{CLAUDE_PLUGIN_ROOT}/', line)
                proc = self.bash(line, encoded_command(tool, data), env=env)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn(MARKER, proc.stderr.decode("utf-8"))
        proc = self.bash(declaration(doc, "claude", "SessionStart", START_MATCHER)["command"], env=env)
        self.assertEqual((proc.returncode, proc.stdout), (0, b""), proc.stderr)


class InstalledAgyTests(unittest.TestCase):
    def setUp(self):
        self.h = IsolatedHome(self)
        self.h.install("antigravity")

    def test_install_leaves_workspace_alone_and_preserves_other_entries(self):
        path = self.h.cwd / ".agents/hooks.json"
        path.parent.mkdir()
        original = b'{"other-helper":{"PreToolUse":[]}}\n'
        path.write_bytes(original)
        config = self.h.configs["antigravity"]
        current = self.h.config("antigravity")
        current["other-helper"] = {"PreToolUse": []}
        config.write_text(json.dumps(current), encoding="utf-8")
        self.h.install("antigravity")
        self.assertEqual(self.h.config("antigravity")["other-helper"], {"PreToolUse": []})
        self.assertEqual(path.read_bytes(), original)

    def test_configured_global_declaration(self):
        handler = self.h.declared("antigravity", "PreToolUse", "run_command|manage_task")
        self.assertEqual(handler["timeout"], 15)
        self.assertEqual(handler["type"], "command")
        self.assertNotIn("`", handler["command"])
        self.assertIn("-I -X utf8 -B", handler["command"])
        self.assertIn((self.h.package("antigravity") / "scripts/antigravity_backtick_guard.py").as_posix(),
                      handler["command"].replace("\\", "/"))
        if os.name == "nt":
            self.assertIn("|| exit /b 0", handler["command"])

    @unittest.skipUnless(os.name == "nt", "validates cmd.exe command parsing")
    def test_configured_cmd_hook_blocks_allows_and_survives_missing_adapter(self):
        handler = self.h.declared("antigravity", "PreToolUse", "run_command|manage_task")
        line = handler["command"]
        # /S strips the outer quotes. Pass the original declaration to cmd intact.
        cmd = '"' + os.environ["COMSPEC"] + '" /d /s /c "' + line + '"'
        for payload, deny in [(_make_payload(PROBE), True), (_make_payload('Write-Output "a`tb"'), False),
                              (_make_payload("echo plain"), False), (_make_manage_task_payload("send_input", PROBE), True),
                              (_make_manage_task_payload("send_input", "y\n"), False)]:
            with self.subTest(tool=payload["toolCall"]["name"], deny=deny):
                proc = self.h.run(cmd, json.dumps(payload).encode("utf-8"))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                if deny:
                    result = json.loads(proc.stdout)
                    self.assertEqual(result["decision"], "deny")
                    self.assertIn(MARKER, result["reason"])
                else:
                    self.assertEqual(proc.stdout, b"")
        (self.h.package("antigravity") / "scripts/antigravity_backtick_guard.py").unlink()
        proc = self.h.run(cmd, json.dumps(_make_payload(PROBE)).encode("utf-8"))
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))
        python = Path(sys.executable).resolve().as_posix()
        missing = cmd.replace(python, (self.h.root / "missing-python.exe").as_posix(), 1)
        self.assertNotEqual(missing, cmd)
        proc = self.h.run(missing, json.dumps(_make_payload(PROBE)).encode("utf-8"))
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))


class InstalledCodexTests(unittest.TestCase):
    def test_configured_hook_uses_native_runner_and_returns_only_deny(self):
        h = IsolatedHome(self)
        h.install("codex")
        rule = h.declared("codex", "PreToolUse", "^Bash$")
        self.assertEqual(rule["timeout"], 30)
        if os.name == "nt":
            self.assertIn("-File", rule["command"])
            for command, deny in [(PROBE, True), ('Write-Output "a`tb"', False), ("echo plain", False)]:
                with self.subTest(command=command):
                    cmd = '"' + os.environ["COMSPEC"] + '" /d /s /c "' + rule["command"] + '"'
                    proc = h.run(cmd, encoded_command("Bash", command))
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    if deny:
                        result = json.loads(proc.stdout)["hookSpecificOutput"]
                        self.assertEqual(result["permissionDecision"], "deny")
                        self.assertIn(MARKER, result["permissionDecisionReason"])
                    else:
                        self.assertEqual(proc.stdout, b"")
        else:
            for command, deny in [(BASH_CASE, True), ("echo plain", False)]:
                proc = h.run(["/bin/sh", "-c", rule["command"]], encoded_command("Bash", command))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                if deny:
                    self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
                else:
                    self.assertEqual(proc.stdout, b"")


class InstallRoundtripTests(unittest.TestCase):
    def test_three_hosts_preserve_other_entries_and_leave_codex_trust_to_user(self):
        h = IsolatedHome(self)
        trust = h.configs["codex"].parent / "config.toml"
        trust.write_bytes(b"# existing configuration\n")
        other_command = {"matcher": "OtherTool", "hooks": [{"type": "command", "command": "echo foreign"}]}
        for host in ("claude", "codex", "antigravity"):
            with self.subTest(host=host):
                path = h.configs[host]
                path.parent.mkdir(exist_ok=True, parents=True)
                old = ({"other-helper": {"PreToolUse": [other_command]}} if host == "antigravity"
                       else {"hooks": {"PreToolUse": [other_command]}, "example": True} if host == "claude"
                       else {"hooks": {"PreToolUse": [other_command]}})
                path.write_text(json.dumps(old), encoding="utf-8")
                config = h.install(host)
                self.assertEqual(h.install(host), config)
                self.assertTrue((h.package(host) / "LICENSE").is_file())
                p = h.manage("doctor", host)
                report = json.loads(p.stdout)
                self.assertEqual(report["synthetic"], "passed")
                self.assertNotIn(str(h.home).encode(), p.stdout)
                self.assertNotIn(b"echo foreign", p.stdout)
                self.assertNotIn(b"trusted_hash", path.read_bytes())
                self.assertEqual(trust.read_bytes(), b"# existing configuration\n")
                if host == "codex":
                    self.assertIn("/hooks", report["trust"])
                h.manage("uninstall", host)
                self.assertEqual(h.config(host), old)
                self.assertFalse(h.package(host).exists())
        self.assertEqual(trust.read_bytes(), b"# existing configuration\n")

    def test_doctor_reports_drift_since_operator_confirmed_version(self):
        h = IsolatedHome(self)
        h.install("codex")
        h.manage("record-probe", "codex", "--host-version", "1.2.3")
        report = json.loads(h.manage("doctor", "codex", "--host-version", "1.2.4").stdout)
        self.assertEqual(report["last_probe_version"], "1.2.3")
        self.assertEqual(report["host_version"], "1.2.4")
        self.assertIs(report["version_drift"], True)
        self.assertTrue(report["warnings"])

    def test_broken_json_is_preserved(self):
        h = IsolatedHome(self)
        for host, path in h.configs.items():
            with self.subTest(host=host):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"{invalid json")
                self.assertNotEqual(h.manage("install", host, check=False).returncode, 0)
                self.assertEqual(path.read_bytes(), b"{invalid json")
