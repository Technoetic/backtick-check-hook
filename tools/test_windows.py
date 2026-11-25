"""Run discovery in a private Windows console at a verified input/output code page."""
import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TimedCase(unittest.TestCase):
    """Run the original assertion in a child so a stalled regex cannot stop discovery."""

    def __init__(self, case):
        super().__init__("runTest")
        self.case = case

    def id(self):
        return self.case.id()

    def __str__(self):
        return str(self.case)

    def runTest(self):
        args = [sys.executable, "-X", "utf8", "-B", "-m", "unittest", self.case.id()]
        try:
            result = subprocess.run(args, cwd=Path(__file__).resolve().parents[1] / "tests",
                                    capture_output=True, encoding="utf-8", errors="replace", timeout=8)
        except subprocess.TimeoutExpired:
            self.fail("Original speed test exceeded the 8-second subprocess deadline")
        self.assertEqual(result.returncode, 0, result.stderr)


def legacy_discovery():
    def bounded(suite):
        for case in suite:
            if isinstance(case, unittest.TestSuite):
                yield from bounded(case)
            elif case.id().startswith("test_ps_publish_guard.SpeedTests."):
                yield TimedCase(case)
            else:
                yield case

    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(bounded(suite)))
    return 0 if result.wasSuccessful() else 1


def worker(codepage):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel.SetConsoleCP(codepage) or not kernel.SetConsoleOutputCP(codepage):
        raise ctypes.WinError(ctypes.get_last_error())
    def pages():
        return kernel.GetConsoleCP(), kernel.GetConsoleOutputCP()
    expected = (codepage, codepage)
    if pages() != expected:
        raise RuntimeError("Unable to set the requested console code pages")
    print("Before:", pages(), "Python:", sys.version.split()[0], flush=True)
    # The selected runtime is also the first Python available to hook subprocesses.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("GEMINI_", "GOOGLE_"))}
    with tempfile.TemporaryDirectory(prefix="backtick suite ") as tmp:
        home = Path(tmp) / "test home"
        home.mkdir()
        for name, sub in (("HOME", ""), ("USERPROFILE", ""), ("APPDATA", "roaming"),
                          ("LOCALAPPDATA", "local"), ("TEMP", "tmp"), ("TMP", "tmp"),
                          ("CODEX_HOME", ".codex"), ("CLAUDE_CONFIG_DIR", ".claude")):
            target = home / sub
            target.mkdir(exist_ok=True)
            env[name] = str(target)
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-X", "utf8", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
        if sys.version_info < (3, 11):
            command = [sys.executable, "-X", "utf8", "-B", __file__, "--legacy-discovery"]
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env)
    print("After:", pages(), "test exit:", result.returncode, flush=True)
    if pages() != expected:
        raise RuntimeError("Console code page changed during the test")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codepage", type=int, choices=[949, 65001])
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows console required")
    if args.worker:
        return worker(args.codepage)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    cmd = [sys.executable, "-X", "utf8", "-B", __file__, str(args.codepage), "--worker"]
    with subprocess.Popen(cmd, startupinfo=startup, creationflags=subprocess.CREATE_NEW_CONSOLE,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
        for line in proc.stdout:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
        return proc.wait()


if __name__ == "__main__":
    if sys.argv[1:] == ["--legacy-discovery"]:
        raise SystemExit(legacy_discovery())
    raise SystemExit(main())
