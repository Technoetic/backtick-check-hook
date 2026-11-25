"""Run self-check diagnostics against hooks inside isolated test installations."""
import json
import os
import sys
import time
import unittest

from isolated_home import IsolatedHome
from test_bash_quote_guard import BASH, g


@unittest.skipUnless(BASH, "no usable bash (Git Bash) on this machine")
class InstalledSelfTestTests(unittest.TestCase):
    """--self-test: 설정에 걸린 훅 명령을 실제로 돌려 보고, 막지 못하면 경고한다."""

    def setUp(self):
        self.h = IsolatedHome(self)
        self.h.install("claude")
        self.env = self.h.env
        self.good = self.h.declared("claude", "PreToolUse", "Bash|Monitor")["command"]

    def settings(self, name, hook=None, matcher="Bash|Monitor", raw=None):
        path = os.path.join(self.h.root, name)
        with open(path, "w", encoding="utf-8") as f:
            if raw is not None:
                f.write(raw)
            else:
                entry = [] if hook is None else [{"matcher": matcher, "hooks": [hook]}]
                json.dump({"hooks": {"PreToolUse": entry}}, f)
        return path

    def check(self, *paths, **kwargs):
        return g.self_test(list(paths), bash=BASH, env=self.env, **kwargs)

    def test_working_hook_reports_nothing(self):
        path = self.settings("ok.json", {"type": "command", "timeout": 15, "command": self.good})
        self.assertEqual(self.check(path), [])
        # 같은 항목이 두 설정에 있어도 한 번만 본다
        again = self.settings("ok2.json", {"type": "command", "timeout": 15, "command": self.good})
        self.assertEqual(self.check(path, again, os.path.join(self.h.root, "missing.json")), [])

    def test_matchers_are_read_the_way_claude_code_reads_them(self):
        for matcher in ("(Bash|Monitor)", "^(Bash|Monitor)$", "Bash.*|Mon", "*", ""):
            with self.subTest(matcher=matcher):
                path = self.settings("m.json", {"type": "command", "command": self.good}, matcher=matcher)
                self.assertEqual(self.check(path), [])
        broken = self.settings("m.json", {"type": "command", "command": self.good}, matcher="Bash|Monitor|[")
        problems = self.check(broken)
        self.assertTrue(any("is not a valid pattern, so that hook never runs" in p for p in problems), problems)
        self.assertIn("no working hook covers the Bash tool", problems)
        self.assertEqual((g._matcher_covers("Bash", "BashOutput"), g._matcher_covers("Bash.*", "BashOutput")), (False, True))

    def test_no_hook_is_reported(self):
        problems = self.check(self.settings("none.json"))
        self.assertEqual(len(problems), 1)
        self.assertIn("no PreToolUse hook runs bash_quote_guard.py", problems[0])

    def test_hook_that_cannot_find_the_guard_is_reported(self):
        missing = self.h.root.as_posix() + "/nowhere/bash_quote_guard.py"
        broken = 'python -I -X utf8 -B "%s" --block-code=42; [ $? -eq 42 ] && exit 2; exit 0' % missing
        problems = self.check(self.settings("broken.json", {"type": "command", "command": broken}))
        self.assertEqual(len([p for p in problems if "did not block a command with a live backtick" in p]), 2)
        self.assertIn("no working hook covers the Bash tool", problems)
        self.assertIn("no working hook covers the Monitor tool", problems)
        self.assertFalse(any(p.startswith("note: ") for p in problems))

    def test_hook_that_blocks_everything_is_reported(self):
        always = "exit 2  # bash_quote_guard.py"
        problems = self.check(self.settings("always.json", {"type": "command", "command": always}))
        self.assertTrue(any("blocked a harmless command" in p for p in problems), problems)

    def test_async_and_narrow_matcher_are_reported(self):
        hook = {"type": "command", "command": self.good, "async": True}
        problems = self.check(self.settings("async.json", hook, matcher="Bash"))
        self.assertTrue(any("marked async" in p for p in problems), problems)
        self.assertIn("no working hook covers the Monitor tool", problems)
        narrow = self.settings("narrow.json", {"type": "command", "command": self.good}, matcher="Bash")
        self.assertEqual(self.check(narrow), ["no working hook covers the Monitor tool"])

    def test_broken_settings_file_is_a_note_when_another_file_protects(self):
        bad = self.settings("bad.json", raw="{ not json")
        self.assertTrue(any("not valid JSON" in p for p in self.check(bad)))
        good = self.settings("ok.json", {"type": "command", "timeout": 15, "command": self.good})
        problems = self.check(bad, good)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("note: settings file is not valid JSON"), problems)
        text = g.format_self_test(problems)
        self.assertTrue(text.startswith("[bash-quote-guard] NOTICE: the Bash backtick guard works in this session"))
        self.assertNotIn("note: ", text)
        self.assertIn("사용자에게 알리세요", text)

    def test_two_different_guard_commands_are_a_note(self):
        one = self.settings("one.json", {"type": "command", "command": self.good})
        two = self.settings("two.json", {"type": "command", "command": self.good + " "})
        problems = self.check(one, two)
        self.assertEqual(len(problems), 1)
        self.assertIn("2 different guard commands are wired", problems[0])

    def test_hanging_hook_does_not_hold_the_session_start(self):
        hang = "while :; do :; done  # bash_quote_guard.py"
        started = time.perf_counter()
        problems = self.check(self.settings("hang.json", {"type": "command", "command": hang}), budget=1.5)
        self.assertLess(time.perf_counter() - started, 10)
        self.assertTrue(any("did not finish within 1.5 seconds" in p for p in problems), problems)

    def test_cli_distinguishes_failed_discovery_from_healthy_plugin(self):
        package = self.h.package("claude")
        path = package / "hooks/hooks.json"
        working = path.read_bytes()
        path.write_bytes(b'{"hooks": {}}')
        cmd = [sys.executable, "-I", "-X", "utf8", "-B", str(package / "scripts/bash_quote_guard.py"), "--self-test"]
        proc = self.h.run(cmd)
        self.assertEqual(proc.returncode, g.SELF_TEST_FAILED)
        self.assertIn("WARNING", proc.stdout.decode("utf-8"))
        self.assertIn("no PreToolUse hook runs bash_quote_guard.py", proc.stdout.decode("utf-8"))
        self.assertIn("사용자에게 알리세요", proc.stdout.decode("utf-8"))
        path.write_bytes(working)
        proc = self.h.run(cmd)
        self.assertEqual((proc.returncode, proc.stdout), (10, b""))
