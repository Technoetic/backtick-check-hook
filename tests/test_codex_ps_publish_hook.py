"""Exercise the Codex PreToolUse adapter on Windows PowerShell 5.1."""
import codecs
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ADAPTER = SCRIPTS / "codex_ps_publish_hook.ps1"
GUARD = SCRIPTS / "ps_publish_guard.py"
POWERSHELL = shutil.which("powershell.exe")
PROBE = 'if ($false) { gh release create v0.0.0-probe --notes "probe `x` text" }'


def payload(command, tool="Bash", **metadata):
    event = dict(metadata, hook_event_name="PreToolUse", tool_name=tool,
                 tool_input={"command": command})
    return json.dumps(event, ensure_ascii=False).encode("utf-8")


@unittest.skipUnless(POWERSHELL, "requires Windows PowerShell")
class CodexPublishHookTests(unittest.TestCase):
    def run_hook(self, data, env=None, *, script_args=(ADAPTER,), creationflags=0):
        proc = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", *script_args], input=data, capture_output=True, env=env, timeout=30,
            creationflags=creationflags,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def assert_probe_denied(self, decision):
        result = decision.get("hookSpecificOutput", {})
        self.assertEqual(result.get("permissionDecision"), "deny")
        self.assertIn("1:61, 1:63", result["permissionDecisionReason"])

    def test_deny_without_attached_console(self):
        # Windows PowerShell 5.1 can exit before -File when started with
        # DETACHED_PROCESS. Detach the running host, then call the real script.
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = Path(tmp) / "detach.ps1"
            wrapper.write_text("""param($Adapter)
$ErrorActionPreference = 'Stop'
Add-Type -Name ConsoleTest -Namespace Win32 -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern bool FreeConsole();
[DllImport("kernel32.dll")] public static extern uint GetConsoleCP();
'@
[void][Win32.ConsoleTest]::FreeConsole()
if ([Win32.ConsoleTest]::GetConsoleCP() -ne 0) { throw 'Still attached to a console' }
& $Adapter
""", encoding="ascii")
            self.assert_probe_denied(self.run_hook(payload(PROBE), script_args=(wrapper, ADAPTER)))

    def test_deny_with_utf8_bom(self):
        self.assert_probe_denied(self.run_hook(codecs.BOM_UTF8 + payload(PROBE)))

    def test_deny_matches_shared_guard_for_literal_and_escaped_backticks(self):
        multiline = 'Write-Output "한글"\r\n\tgh issue create --body "⚡한글 `문서`"'
        for command, escaped in [(PROBE, False), (multiline, True)]:
            with self.subTest(command=command, escaped=escaped):
                direct = subprocess.run([sys.executable, str(GUARD), "--raw", "--block-code=42"],
                                        input=command.encode("utf-8"), capture_output=True, timeout=30)
                self.assertEqual(direct.returncode, 42)
                data = payload(command)
                if escaped:
                    data = data.replace(b"`", br"\u0060")
                decision = self.run_hook(data)["hookSpecificOutput"]
                self.assertEqual(decision["hookEventName"], "PreToolUse")
                self.assertEqual(decision["permissionDecision"], "deny")
                self.assertEqual(decision["permissionDecisionReason"], direct.stderr.decode("utf-8"))

    def test_allow_normal_powershell_escape_and_unrelated_tools(self):
        for data in [payload('Write-Output "a`tb"'), payload("echo plain"),
                     payload("git commit -m 'use `backticks`'"), payload(PROBE, tool="apply_patch"),
                     payload(PROBE, tool="bash")]:
            with self.subTest(data=data):
                self.assertNotEqual(self.run_hook(data).get("hookSpecificOutput", {}).get("permissionDecision"),
                                    "deny")

    def test_python_starts_only_for_shell_command_containing_a_backtick(self):
        # A temporary executable with the Python name records each launch. This
        # also distinguishes an actual fast path from starting Python and allowing.
        compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework/v4.0.30319/csc.exe"
        if not compiler.is_file():
            self.skipTest("requires the .NET Framework C# compiler")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            marker = folder / "python-input.txt"
            source = folder / "Probe.cs"
            source.write_text('''using System;
using System.IO;
class Probe {
    static int Main() {
        using (var file = File.Create(Environment.GetEnvironmentVariable("CODEX_TEST_MARKER")))
            Console.OpenStandardInput().CopyTo(file);
        return 2;
    }
}
''', encoding="ascii")
            subprocess.run([str(compiler), "/nologo", "/out:" + str(folder / "python.exe"), str(source)],
                           check=True, capture_output=True, timeout=30)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], CODEX_TEST_MARKER=str(marker))
            for data in [payload("echo plain"), payload("echo plain", other_field="other`field"),
                         payload(r'git commit -m "literal \u0060"'), payload(PROBE, tool="apply_patch")]:
                with self.subTest(data=data):
                    self.run_hook(data, env)
                    self.assertFalse(marker.exists(), "Python started on the fast path")
            # A child exit of 2 (e.g. missing guard) must pass. Its stdin must
            # preserve all original UTF-8 bytes, including CRLF and tabs.
            command = '\t# 한글\r\n' + PROBE
            # With an inherited CP 65001 console, .NET prefixes redirected
            # stdin with a BOM. Isolate the host for this byte comparison.
            answer = self.run_hook(payload(command), env, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertNotEqual(answer.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
            self.assertEqual(marker.read_bytes(), command.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
