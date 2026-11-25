"""Run discovery in a private Windows console at a verified input/output code page."""
import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile


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
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("GEMINI_", "GOOGLE_", "BASH_FUNC_"))
           and k.upper() not in ("BASH_ENV", "ENV", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR")}
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
            print("Unsupported Python: testing installation refusal and doctor only.", flush=True)
            command.extend(["-p", "test_install_minimum.py"])
        else:
            print("Timing scale:", env.get("BACKTICK_TIMING_SCALE", "1"), flush=True)
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
    raise SystemExit(main())
