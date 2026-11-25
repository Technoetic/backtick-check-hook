"""Read and execute the declarations written into a temporary home."""
import base64
from contextlib import redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import unittest
from unittest import mock

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
        self.assertEqual(set(rule), {"type", "command", "timeout", "onFailure"})
        self.assertEqual(rule["onFailure"], "continue")
        self.assertEqual((rule["type"], rule["timeout"]), ("command", 15))
        self.assertTrue(line.startswith("export LC_ALL=C; exec /bin/bash "))
        self.assertNotIn("\\", line)
        launcher = (self.package / "hooks/python.sh").read_text(encoding="utf-8")
        self.assertIn("*'`'*|*u0060*)", launcher)
        self.assert_pinned_asset(line, "scripts/" + script)
        self.assertNotIn("CLAUDE_PROJECT_DIR", line)
        self.assertIn("-I -X utf8 -B", launcher)
        self.assertIn("--block-code=42", launcher)

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
        self.assertIn(" session ", line)
        self.assertIn("--self-test --installed", (self.package / "hooks/python.sh").read_text(encoding="utf-8"))
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

    def test_session_start_warns_when_real_registration_is_removed(self):
        # A similarly named handler from another installation must not be run.
        marker = self.h.cwd / "foreign-hook-ran"
        self.settings["hooks"]["PreToolUse"] = [{"matcher": "Bash|Monitor", "hooks": [{
            "type": "command", "command": ": > foreign-hook-ran # bash_quote_guard.py"}]}]
        self.h.configs["claude"].write_text(json.dumps(self.settings), encoding="utf-8")
        proc = self.bash(self.session()["command"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("WARNING", proc.stdout.decode("utf-8"))
        self.assertIn("no PreToolUse hook", proc.stdout.decode("utf-8"))
        self.assertFalse(marker.exists())

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
        resolver.unlink()
        proc = self.bash(line)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("self-test code 127", proc.stdout.decode("utf-8"))
        proc = self.bash(self.pre("Bash|Monitor")["command"], encoded_command("Bash", BASH_CASE))
        self.assertEqual(proc.stdout, b"")
        self.assertNotEqual(proc.returncode, 2)
        self.assertEqual(self.pre("Bash|Monitor")["onFailure"], "continue")

    @unittest.skipUnless(os.name == "nt", "Git Bash is required for Windows tests")
    def test_git_bash_is_available(self):
        self.assertTrue(BASH)

    def test_posix_sh_dispatches_installed_and_plugin_hooks(self):
        if os.name == "nt":
            dash = Path(BASH).resolve().parent / "dash.exe"
            if not dash.is_file():
                dash = Path(BASH).resolve().parents[1] / "usr/bin/dash.exe"
        else:
            dash = Path(shutil.which("dash") or "/bin/sh")
        self.assertTrue(dash.is_file(), "requires dash or the POSIX host shell")
        template = json.loads((REPO / "hooks/hooks.json").read_bytes())
        env = dict(self.h.env, CLAUDE_PLUGIN_ROOT=REPO.as_posix())
        for config in (template, self.settings):
            for m, tool, payload, expected in (("Bash|Monitor", "Bash", BASH_CASE, 2),
                                             ("PowerShell", "PowerShell", PROBE, 2),
                                             ("Bash|Monitor", "Bash", "echo plain", 0)):
                with self.subTest(native=config is template, tool=tool, expected=expected):
                    cmd = declaration(config, "claude", "PreToolUse", m)["command"]
                    proc = self.h.run([str(dash), "-c", cmd], encoded_command(tool, payload), env=env)
                    self.assertEqual(proc.returncode, expected, proc.stderr)
                    if expected:
                        self.assertIn(MARKER.encode(), proc.stderr)
            start = declaration(config, "claude", "SessionStart", START_MATCHER)["command"]
            proc = self.h.run([str(dash), "-c", start], env=env)
            self.assertEqual((proc.returncode, proc.stdout), (0, b""), proc.stderr)

    @unittest.skipUnless(os.name == "nt", "Windows hook shell fallback")
    def test_claude_install_and_doctor_require_git_bash(self):
        h = IsolatedHome(self)
        h.env["CLAUDE_CODE_GIT_BASH_PATH"] = str(h.root / "absent/bash.exe")
        refused = h.manage("install", "claude", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(b"require Git Bash", refused.stderr)
        self.assertFalse(h.configs["claude"].exists())
        self.assertFalse(h.package("claude").exists())
        result = h.manage("doctor", "claude", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"require Git Bash", result.stdout)
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        for matcher in ("Bash|Monitor", "PowerShell"):
            rule = self.pre(matcher)
            proc = h.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", rule["command"]],
                         encoded_command("PowerShell", "Get-Date"))
            self.assertNotIn(proc.returncode, (0, 2))
            self.assertEqual(rule["onFailure"], "continue")

    def test_native_start_warns_when_launcher_is_missing(self):
        env = dict(self.h.env, CLAUDE_PLUGIN_ROOT=self.h.root.as_posix())
        template = json.loads((REPO / "hooks/hooks.json").read_bytes())
        line = declaration(template, "claude", "SessionStart", START_MATCHER)["command"]
        proc = self.bash(line, env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"launcher", proc.stdout)

    def test_native_start_warns_when_python_is_too_old(self):
        # Emulate the version query without evaluating a command from the event.
        folder = self.h.root / "bin"
        folder.mkdir()
        name = "python.exe" if os.name == "nt" else "python3"
        shim = folder / name
        shim.write_text("#!/bin/sh\ncase \"$*\" in *sys.version_info*) exit 78 ;; esac\nexit 97\n",
                        encoding="ascii", newline="\n")
        shim.chmod(0o755)
        template = json.loads((REPO / "hooks/hooks.json").read_bytes())
        env = dict(self.h.env, PATH=str(folder) + os.pathsep + self.h.env["PATH"],
                   CLAUDE_PLUGIN_ROOT=REPO.as_posix())
        line = declaration(template, "claude", "SessionStart", START_MATCHER)["command"]
        proc = self.bash(line, env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"Python 3.11 or later", proc.stdout)
        self.assertIn(b"code 78", proc.stdout)

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
        adapter = self.h.package("antigravity") / "scripts/antigravity_backtick_guard.py"
        if os.name == "nt":
            self.assertNotIn('"', handler["command"])
            token = handler["command"].split(" -B ", 1)[1].split(" ", 1)[0]
            self.assertTrue(Path(token).samefile(adapter))
            self.assertIn("|| exit /b 0", handler["command"])
        else:
            self.assertIn(adapter.as_posix(), handler["command"])

    @unittest.skipUnless(os.name == "nt", "requires Windows short path resolution")
    def test_unrepresentable_path_is_refused_before_registration(self):
        h = IsolatedHome(self)
        spec = importlib.util.spec_from_file_location("hook_installer", REPO / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with mock.patch.dict(os.environ, h.env, clear=True), \
                mock.patch("ctypes.windll.kernel32.GetShortPathNameW", return_value=0):
            with self.assertRaisesRegex(installer.InstallError, "8.3"):
                installer.change("antigravity", "install")
        self.assertFalse(h.configs["antigravity"].exists())
        self.assertFalse(h.package("antigravity").exists())

    @unittest.skipUnless(os.name == "nt", "validates cmd.exe command parsing")
    def test_configured_cmd_hook_blocks_allows_and_survives_missing_adapter(self):
        handler = self.h.declared("antigravity", "PreToolUse", "run_command|manage_task")
        line = handler["command"]
        def launch(line):
            cmd = os.environ["COMSPEC"]
            return ('"' + cmd + '" /d /s /c "' + line + '"', [cmd, "/d", "/s", "/c", line])
        for payload, deny in [(_make_payload(PROBE), True), (_make_payload('Write-Output "a`tb"'), False),
                              (_make_payload("echo plain"), False), (_make_manage_task_payload("send_input", PROBE), True),
                              (_make_manage_task_payload("send_input", "y\n"), False)]:
            for cmd in launch(line):
                with self.subTest(tool=payload["toolCall"]["name"], deny=deny, runner=type(cmd).__name__):
                    proc = self.h.run(cmd, json.dumps(payload).encode("utf-8"))
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    if deny:
                        result = json.loads(proc.stdout)
                        self.assertEqual(result["decision"], "deny")
                        self.assertIn(MARKER, result["reason"])
                    else:
                        self.assertEqual(proc.stdout, b"")
        (self.h.package("antigravity") / "scripts/antigravity_backtick_guard.py").unlink()
        python_token = line.split(" -I ", 1)[0]
        missing = line.replace(python_token, "no-such-interpreter.exe", 1)
        for cmd in (*launch(line), *launch(missing)):
            proc = self.h.run(cmd, json.dumps(_make_payload(PROBE)).encode("utf-8"))
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
    def test_install_and_uninstall_verify_the_file_list_of_the_previous_receipt(self):
        h = IsolatedHome(self)
        path = h.configs["codex"]
        for verb in ("install", "uninstall"):
            with self.subTest(verb=verb):
                h.install("codex")
                package = h.package("codex")
                old_file = package / "previous-version.txt"
                old_file.write_bytes(b"old payload")
                receipt = package / "state.json"
                state = json.loads(receipt.read_bytes())
                state["files"][old_file.name] = hashlib.sha256(old_file.read_bytes()).hexdigest()
                receipt.write_text(json.dumps(state), encoding="utf-8")
                h.manage(verb, "codex")
                self.assertFalse(old_file.exists())
                self.assertEqual(path.exists(), verb == "install")

    @unittest.skipUnless(os.name == "nt", "exercises a Windows interpreter path")
    def test_uninstall_can_use_an_interpreter_with_a_percent_in_its_path(self):
        h = IsolatedHome(self)
        h.install("codex")
        venv = h.root / "py%x"
        proc = h.run([sys.executable, "-I", "-m", "venv", "--without-pip", str(venv)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = h.run([str(venv / "Scripts/python.exe"), "-I", "-X", "utf8", "-B",
                      str(REPO / "install.py"), "uninstall", "--host", "codex"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(h.package("codex").exists())

    def test_uninstall_after_config_removal_checks_files_and_leaves_config_absent(self):
        h = IsolatedHome(self)
        h.install("codex")
        h.configs["codex"].unlink()
        package = h.package("codex")
        unknown = package / "other-file.txt"
        unknown.write_text("keep", encoding="utf-8")
        self.assertEqual(h.manage("uninstall", "codex", check=False).returncode, 1)
        self.assertEqual(unknown.read_text(encoding="utf-8"), "keep")
        unknown.unlink()
        h.manage("uninstall", "codex")
        self.assertFalse(h.configs["codex"].exists())
        self.assertFalse(package.exists())

    def test_missing_package_reports_remaining_registration_for_each_host(self):
        h = IsolatedHome(self)
        for host, config in h.configs.items():
            with self.subTest(host=host):
                h.install(host)
                original = config.read_bytes()
                shutil.rmtree(h.package(host))
                result = h.manage("uninstall", host, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn(b"registration", result.stderr)
                self.assertIn(config.name.encode(), result.stderr)
                self.assertEqual(config.read_bytes(), original)
                config.unlink()
                h.manage("uninstall", host)
                self.assertFalse(config.exists())

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
            for invalid in (b"{invalid json", b'{"a":1e400}', b'{"a":Infinity}'):
                with self.subTest(host=host, length=len(invalid)):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(invalid)
                    result = h.manage("install", host, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(b"Traceback", result.stderr)
                    self.assertEqual(path.read_bytes(), invalid)

    def test_recursion_error_preserves_existing_configuration(self):
        home = IsolatedHome(self)
        path = home.configs["codex"]
        path.parent.mkdir(parents=True, exist_ok=True)
        original = b'{"foreign":{"id":1}}\n'
        path.write_bytes(original)
        main = runpy.run_path(str(REPO / "install.py"))["main"]
        message = io.StringIO()
        # JSON libraries reach their recursion limit at different depths.
        with mock.patch.dict(os.environ, home.env, clear=True), \
                mock.patch.object(sys, "argv", ["install.py", "install", "--host", "codex"]), \
                mock.patch.object(json, "loads", side_effect=RecursionError), redirect_stderr(message):
            self.assertEqual(main(), 1)
        self.assertEqual(message.getvalue().strip(), "RecursionError")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(home.package("codex").exists())

    def test_supported_nested_json_survives_install_and_uninstall(self):
        home = IsolatedHome(self)
        path = home.configs["codex"]
        path.parent.mkdir(parents=True, exist_ok=True)
        value = 1
        for _ in range(32):
            value = [value]
        original = {"foreign": value}
        path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(home.install("codex")["foreign"], value)
        home.manage("uninstall", "codex")
        self.assertEqual(home.config("codex"), original)
