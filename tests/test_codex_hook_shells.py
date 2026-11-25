"""Run the unchanged installed declaration through the Windows hook dispatchers."""
import json
import os
from pathlib import Path
import unittest

from isolated_home import IsolatedHome, MARKER, declaration, encoded_command
from test_codex_ps_publish_hook import PROBE


@unittest.skipUnless(os.name == "nt", "Windows hook dispatchers")
class WindowsHookDispatchTests(unittest.TestCase):
    def test_cmd_and_powershell_dispatch_the_installed_line(self):
        home = IsolatedHome(self)
        line = declaration(home.install("codex"), "codex", "PreToolUse", "^Bash$")["command"]
        system = Path(os.environ["SystemRoot"]) / "System32"
        raw_cmd = '"' + str(system / "cmd.exe") + '" /C "' + line + '"'
        shell = str(system / "WindowsPowerShell/v1.0/powershell.exe")
        # CommandExt::raw_arg wraps the cmd line. Other shells get a single
        # argv element containing the declaration after their execution flag.
        for name, argv in [("cmd", raw_cmd), ("powershell", [shell, "-NoProfile", "-Command", line])]:
            for sample, denied in [(PROBE, True), ('Write-Output "a' + chr(96) + 'tb"', False),
                                   ("echo plain", False)]:
                with self.subTest(shell=name, denied=denied, sample=sample):
                    proc = home.run(argv, encoded_command("Bash", sample))
                    self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
                    if denied:
                        body = json.loads(proc.stdout)["hookSpecificOutput"]
                        self.assertEqual(body["permissionDecision"], "deny")
                        self.assertIn(MARKER, body["permissionDecisionReason"])
                    else:
                        self.assertEqual(proc.stdout, b"")
