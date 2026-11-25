"""Translate Codex PreToolUse shell events to the Bash checker protocol."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "Bash":
            return 0
        command = event.get("tool_input", {}).get("command")
        if not isinstance(command, str) or "`" not in command:
            return 0
        guard = Path(__file__).resolve().with_name("bash_quote_guard.py")
        result = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-B", str(guard), "--raw", "--block-code=42"],
            input=command.encode("utf-8"), capture_output=True, timeout=10,
        )
        if result.returncode == 42:
            details = {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                       "permissionDecisionReason": result.stderr.decode("utf-8", "replace")}
            sys.stdout.buffer.write((json.dumps({"hookSpecificOutput": details}) + "\n").encode("utf-8"))
    except (ValueError, TypeError, AttributeError, OSError, subprocess.SubprocessError):
        # A malformed event, broken installation or timeout leaves the host in charge.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
