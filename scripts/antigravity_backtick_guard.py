#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""antigravity_backtick_guard.py - Antigravity PreToolUse(run_command|manage_task) 어댑터.

역할:
  Antigravity의 PreToolUse 훅(표준 입력: camelCase JSON, 차단 시 표준 출력:
  {"decision": "deny", "reason": "..."})과 공용 백틱 검사기
  (ps_publish_guard.py · bash_quote_guard.py) 사이를 잇는 얇은 어댑터다.

동작:
  1. 아래 두 경우에만 명령·입력 문자열을 꺼내 검사한다:
     - toolCall.name == "run_command": args.CommandLine(또는 commandLine/command)
     - toolCall.name == "manage_task"이고 Action(또는 action) == "send_input": args.Input(또는 input)
  2. 문자열에 백틱이 없으면 공용 검사기를 띄우지 않고 즉시 빈 출력(종료 0, 훅 의견 없음)으로
     통과시킨다. (ps_publish_guard.py와 기본 모드의 bash_quote_guard.py 모두 백틱이 없으면 막지 않는다.)
     주의: 빈 JSON({})은 Antigravity가 차단(deny)으로 처리하므로 쓰지 않고, 막지 않을 때는 표준 출력을
     비워 실행 정책(Turbo·Auto·Default·Request Review)의 기본 판정에 그대로 위임한다.
  3. 명령이 실행될 셸을 고른다:
     - 명시적 --shell=powershell|bash CLI 인자가 있으면 그 값을 따른다.
     - Windows(sys.platform == "win32")에서는 기본 PowerShell 실행 환경에 맞춰
       toolCall.args의 Shell/shell 힌트를 무시하고 PowerShell(ps_publish_guard.py)을 쓴다.
     - 그 밖의 OS에서는 toolCall.args의 Shell/shell 힌트(있다면) 또는 기본 Bash(bash_quote_guard.py)를 쓴다.
  4. 해당 공용 검사기를 --raw --block-code=42로 실행해 문자열을 표준 입력으로 넘긴다.
     종료 코드가 정확히 42일 때만 {"decision": "deny", "reason": "<검사기 stderr>"}를 돌려준다.
     그 밖의 종료 코드(0, 파일 없음 2, 예외, 타임아웃)와 어댑터 자신의 오류는 모두 빈 출력(종료 0)으로
     통과시켜 검사기 고장이 작업을 멈추지 않게 한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RUN_COMMAND_TOOL = "run_command"
MANAGE_TASK_TOOL = "manage_task"
BLOCK_CODE = 42
GUARD_TIMEOUT = 10.0
BT = "`"
SCRIPTS_DIR = Path(__file__).resolve().parent
GUARD_FILES = {
    "powershell": "ps_publish_guard.py",
    "bash": "bash_quote_guard.py",
}


def extract_command(payload) -> tuple[str | None, dict]:
    """Antigravity PreToolUse 페이로드에서 run_command 명령 또는 manage_task(send_input) 입력을 꺼낸다."""
    if not isinstance(payload, dict):
        return None, {}
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return None, {}
    name = tool_call.get("name")
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return None, {}
    if name == RUN_COMMAND_TOOL:
        for key in ("CommandLine", "commandLine", "command"):
            value = args.get(key)
            if isinstance(value, str) and value:
                return value, args
        return None, args
    if name == MANAGE_TASK_TOOL:
        action = args.get("Action") or args.get("action")
        if action != "send_input":
            return None, args
        for key in ("Input", "input"):
            value = args.get(key)
            if isinstance(value, str) and value:
                return value, args
        return None, args
    return None, {}


def _normalize_shell_hint(value: str) -> str | None:
    low = os.path.basename(value.strip().strip('"').strip("'")).lower()
    if not low:
        return None
    if "powershell" in low or "pwsh" in low:
        return "powershell"
    if low in ("bash", "bash.exe", "sh", "sh.exe", "zsh", "dash", "ksh"):
        return "bash"
    return None


def select_shell(args: dict | None, *, platform: str | None = None, override: str | None = None) -> str:
    """명령이 실행될 셸('powershell' 또는 'bash')을 결정한다.

    Windows에서는 PowerShell 실행 경로에 맞춰
    도구 인자의 Shell/shell 힌트를 무시하고 PowerShell 검사기를 고른다.
    """
    if override in GUARD_FILES:
        return override
    plat = sys.platform if platform is None else platform
    if plat == "win32":
        return "powershell"
    if isinstance(args, dict):
        for key in ("Shell", "shell"):
            hint = args.get(key)
            if isinstance(hint, str):
                normalized = _normalize_shell_hint(hint)
                if normalized:
                    return normalized
    return "bash"


def run_guard(
    command: str,
    shell: str,
    *,
    scripts_dir: Path | str = SCRIPTS_DIR,
    python_exe: str = sys.executable,
    timeout: float = GUARD_TIMEOUT,
) -> str | None:
    """셸에 맞는 공용 검사기를 --raw --block-code=42로 부른다. 막아야 하면 사유 문자열, 아니면 None."""
    if BT not in command:
        return None
    guard_name = GUARD_FILES.get(shell)
    if not guard_name:
        return None
    guard_path = Path(scripts_dir) / guard_name
    if not guard_path.is_file():
        return None
    try:
        proc = subprocess.run(
            [python_exe, "-I", "-X", "utf8", "-B", str(guard_path), "--raw", f"--block-code={BLOCK_CODE}"],
            input=command.encode("utf-8", "replace"),
            capture_output=True,
            timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != BLOCK_CODE:
        return None
    reason = proc.stderr.decode("utf-8", "replace").strip()
    if not reason:
        tag = "ps-publish-guard" if shell == "powershell" else "bash-quote-guard"
        reason = f"[backtick-check-hook] [{tag}] Blocked a command containing a live backtick."
    return reason


def evaluate_payload(
    payload,
    *,
    platform: str | None = None,
    shell_override: str | None = None,
    scripts_dir: Path | str = SCRIPTS_DIR,
    python_exe: str = sys.executable,
    timeout: float = GUARD_TIMEOUT,
) -> dict | None:
    """Antigravity PreToolUse 페이로드를 판정한다.

    막아야 할 때만 {"decision": "deny", "reason": "..."} 사전을 돌려주고,
    막지 않을 때는 None(의견 없음 -> 빈 표준 출력)을 돌려준다.
    """
    command, args = extract_command(payload)
    if not command:
        return None
    shell = select_shell(args, platform=platform, override=shell_override)
    reason = run_guard(
        command,
        shell,
        scripts_dir=scripts_dir,
        python_exe=python_exe,
        timeout=timeout,
    )
    if reason:
        return {"decision": "deny", "reason": reason}
    return None


def _parse_shell_override(argv: list[str]) -> str | None:
    for arg in argv:
        if arg.startswith("--shell="):
            val = arg.split("=", 1)[1].strip().lower()
            if val in GUARD_FILES:
                return val
    return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    result = None
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", "replace")
        if raw.strip():
            payload = json.loads(raw)
            result = evaluate_payload(
                payload,
                shell_override=_parse_shell_override(argv),
            )
    except Exception:
        result = None
    if result is not None:
        try:
            out = (json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8")
            sys.stdout.buffer.write(out)
            sys.stdout.buffer.flush()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
