"""Helpers for isolated command-line installation and declaration tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.py"
MARKER = "[backtick-check-hook]"


class IsolatedHome:
    def __init__(self, test):
        self.test = test
        tmp = tempfile.TemporaryDirectory(prefix="hook-")
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "테스트 home"
        self.cwd = self.root / "sample workspace"
        self.cwd.mkdir()
        temp_dir = self.root / "temp"
        self.env = {
            k: v for k, v in os.environ.items()
            if not k.upper().startswith(("GEMINI_", "GOOGLE_", "BASH_FUNC_"))
            and k.upper() not in ("BASH_ENV", "ENV", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR")
        }
        for key, directory in {
            "HOME": self.home, "USERPROFILE": self.home,
            "APPDATA": self.home / "roaming", "LOCALAPPDATA": self.home / "local",
            "TEMP": temp_dir, "TMP": temp_dir, "TMPDIR": temp_dir,
            "CODEX_HOME": self.home / ".codex", "CLAUDE_CONFIG_DIR": self.home / ".claude",
            "XDG_CONFIG_HOME": self.home / ".config", "XDG_DATA_HOME": self.home / ".local/share",
        }.items():
            directory.mkdir(parents=True, exist_ok=True)
            self.env[key] = str(directory)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + self.env["PATH"]
        self.configs = {
            "claude": self.home / ".claude/settings.json",
            "codex": self.home / ".codex/hooks.json",
            "antigravity": self.home / ".gemini/config/hooks.json",
        }

    def run(self, argv, data=b"", *, env=None, timeout=45):
        return subprocess.run(argv, input=data, capture_output=True, timeout=timeout,
                              cwd=self.cwd, env=self.env if env is None else env)

    def manage(self, verb, host, *options, check=True):
        proc = self.run([sys.executable, "-I", "-X", "utf8", "-B", str(INSTALLER), verb,
                         "--host", host, *options])
        if check:
            self.test.assertEqual(proc.returncode, 0, (proc.stdout, proc.stderr))
        return proc

    def install(self, host):
        self.manage("install", host)
        return self.config(host)

    def config(self, host):
        data = self.configs[host].read_bytes()
        self.test.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        return json.loads(data.decode("utf-8"))

    def package(self, host):
        return self.configs[host].parent / "backtick-check-hook"

    def declared(self, host, event, matcher):
        return declaration(self.config(host), host, event, matcher)


def declaration(doc, host, event, matcher):
    entries = doc["backtick-check-hook" if host == "antigravity" else "hooks"][event]
    matching = [handler for group in entries if group["matcher"] == matcher
                for handler in group["hooks"]]
    if len(matching) != 1:
        raise AssertionError(f"expected one {event} handler for {matcher}, found {len(matching)}")
    return matching[0]


def encoded_command(tool, command):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                       "tool_input": {"command": command}}, ensure_ascii=False).encode("utf-8")
