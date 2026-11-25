"""Exercise published input through each available PowerShell parser and Windows adapter."""
import json
import os
import shutil
import subprocess
import unittest

from isolated_home import MARKER
from test_codex_ps_publish_hook import ADAPTER, PROBE, payload
from test_ps_publish_guard import ALLOW, BLOCK, _cases, g


PARSER = r"""
$ErrorActionPreference = 'Stop'
$encoding = [Text.UTF8Encoding]::new($false)
$reader = [IO.StreamReader]::new([Console]::OpenStandardInput(), $encoding)
$cases = ConvertFrom-Json -InputObject $reader.ReadToEnd()
$result = foreach ($case in $cases) {
    $tokens = $null
    $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseInput($case.text, [ref]$tokens, [ref]$errors)
    $comments = @($tokens | Where-Object Kind -eq 'Comment')
    $heres = @($tokens | Where-Object { $_.Kind -in 'HereStringLiteral', 'HereStringExpandable' })
    [PSCustomObject]@{ name=$case.name; comments=$comments.Count; hereStrings=$heres.Count }
}
[PSCustomObject]@{ major=$PSVersionTable.PSVersion.Major; tokens=@($result) } | ConvertTo-Json -Compress -Depth 3
"""


class PowerShellParserTests(unittest.TestCase):
    def check_parser(self, exe, major):
        cases = []
        expected = {}
        for table, name, comments, here_count, denied in [
            (BLOCK, "comment-after-closing-quote", 1, 0, True),
            (BLOCK, "hash-after-equals-is-text", 0, 0, True),
            (BLOCK, "hash-inside-bare-word", 0, 0, True),
            (ALLOW, "comment-after-paren", 1, 0, False),
            (ALLOW, "comment-after-index", 1, 0, False),
            (ALLOW, "comment-after-type-literal", 1, 0, False),
            (ALLOW, "sq-here-string", 0, 1, False),
            (BLOCK, "dq-here-string", 0, 1, True),
        ]:
            command = _cases(table)[name]
            self.assertEqual(g.find_problem(command) is not None, denied, name)
            cases.append({"name": name, "text": command})
            expected[name] = (comments, here_count)
        proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", PARSER],
                              input=json.dumps(cases).encode(), capture_output=True, timeout=40)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["major"], major)
        self.assertEqual({r["name"]: (r["comments"], r["hereStrings"]) for r in result["tokens"]}, expected)

    @unittest.skipUnless(os.name == "nt", "requires Windows PowerShell")
    def test_windows_powershell_parser(self):
        self.check_parser("powershell.exe", 5)

    def test_powershell_seven_parser(self):
        exe = os.environ.get("BACKTICK_TEST_PWSH") or shutil.which("pwsh")
        if not exe:
            self.skipTest("PowerShell 7 executable not installed")
        self.check_parser(exe, 7)

    @unittest.skipUnless(os.name == "nt", "validates the Windows PowerShell adapter")
    def test_powershell_seven_runs_codex_adapter(self):
        exe = os.environ.get("BACKTICK_TEST_PWSH") or shutil.which("pwsh")
        if not exe:
            self.skipTest("PowerShell 7 executable not installed")
        for text, denied in [(PROBE, True), ('Write-Output "a`tb"', False), ("echo plain", False)]:
            with self.subTest(command=text):
                proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                       "-File", str(ADAPTER)], input=payload(text), capture_output=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                if denied:
                    result = json.loads(proc.stdout)["hookSpecificOutput"]
                    self.assertEqual(result["permissionDecision"], "deny")
                    self.assertIn(MARKER, result["permissionDecisionReason"])
                    self.assertIn("1:61, 1:63", result["permissionDecisionReason"])
                else:
                    self.assertEqual(proc.stdout, b"")
