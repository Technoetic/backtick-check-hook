"""Install, check and remove a per-user backtick-check-hook registration."""
import argparse
import base64
from contextlib import contextmanager
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile

NAME = "backtick-check-hook"
ROOT = Path(__file__).resolve().parent
ON_WINDOWS = os.name == "nt"
WINDOWS_SHELL = Path(os.environ.get("SystemRoot", "/")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
PAYLOADS = {
    "claude": ("scripts/bash_quote_guard.py", "scripts/ps_publish_guard.py", ".claude-plugin/plugin.json"),
    "codex": ("scripts/ps_publish_guard.py", "scripts/codex_ps_publish_hook.ps1") if ON_WINDOWS else
             ("scripts/bash_quote_guard.py", "scripts/codex_posix_hook.py"),
    "antigravity": ("scripts/antigravity_backtick_guard.py",
                    "scripts/ps_publish_guard.py" if ON_WINDOWS else "scripts/bash_quote_guard.py"),
}
MARKER = "state.json"
MIN_PYTHON = (3, 11)
PYTHON_REQUIREMENT = "Python 3.11 or newer is required for these hooks."


class InstallError(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(obj):
    return (json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InstallError("Duplicate JSON key; inspect the configuration.")
        result[key] = value
    return result


def finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise InstallError("Non-finite JSON number; inspect the configuration.")
    return number


def read_object(raw):
    obj = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_keys,
                     parse_constant=finite_number, parse_float=finite_number)
    if not isinstance(obj, dict):
        raise InstallError("Expected a JSON object.")
    return obj


def location(host):
    home = Path.home()
    if host == "claude":
        path = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")) / "settings.json"
    elif host == "codex":
        path = Path(os.environ.get("CODEX_HOME", home / ".codex")) / "hooks.json"
    else:
        path = home / ".gemini/config/hooks.json"
    if not path.is_absolute():
        raise InstallError("The host configuration directory must be absolute.")
    return path


def read_config(path):
    if path.is_symlink():
        raise InstallError("The configuration is a symbolic link; inspect it manually.")
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def quoted_path(path, *, powershell=False):
    text = path.as_posix()
    forbidden = '"%!\r\n'
    if powershell:
        forbidden += '$' + chr(96) + '\u201c\u201d\u201e'
    if any(ch in text for ch in forbidden):
        raise InstallError("The installation path cannot be represented in a Windows command hook.")
    return '"' + text + '"'


def unquoted_windows_path(path, advice="The Windows hook needs an unquoted absolute path. Use a directory "
                          "without spaces or shell metacharacters, or with a usable Windows 8.3 name."):
    """Spell an existing absolute path without cmd metacharacters or quotes."""
    token = path.as_posix()
    safe = r"[A-Za-z]:/[\w./~-]+"
    if re.fullmatch(safe, token):
        return token
    import ctypes
    get_short = ctypes.windll.kernel32.GetShortPathNameW
    size = get_short(str(path), None, 0)
    if size:
        buf = ctypes.create_unicode_buffer(size)
        if 0 < get_short(str(path), buf, size) < size:
            short = Path(buf.value)
            if re.fullmatch(safe, short.as_posix()) and short.samefile(path):
                return short.as_posix()
    raise InstallError(advice)


def bash_path(path):
    text = path.as_posix()
    if any(ch in text for ch in ('"', "$", chr(96), "\\", "\n", "\r")):
        return shlex.quote(text)
    return '"' + text + '"'


def claude_command(template, dest, python):
    # MSYS may transcode a -c argument before Bash sees LC_ALL=C. Pin the
    # original UTF-8 bytes once, without launching a decoder in Git Bash.
    special = {}
    for key, path in (("hook_root", dest), ("hook_python", python)):
        text = path.as_posix()
        if ON_WINDOWS and (not text.isascii() or any(ch in text for ch in (chr(96), '"', '$', '\n', '\r'))):
            special[key] = text.encode("utf-8")
    root = r'"\$\{CLAUDE_PLUGIN_ROOT\}/([^"]+)"'
    interpreter = '"$hook_python"' if "hook_python" in special else bash_path(python)
    def asset(m):
        return '"${hook_root}/' + m[1] + '"' if "hook_root" in special else bash_path(dest / m[1])
    command = (" --python " + interpreter + " ").join(re.sub(root, asset, part)
                                                     for part in template.split(" --discover ", 1))
    if not special:
        return command
    # A quoted space is backslash-space in the C locale. Take its first
    # character for printf %b's octal escapes, keeping the declaration itself
    # free of literal backslashes across Windows command-line dispatchers.
    bash = ["printf -v esc %q ' '", "esc=${esc%?}"]
    posix = []
    literal = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 /:.-_"
    for key, data in special.items():
        octets = "".join(chr(b) if b in literal
                         else "${esc}0" + format(b, "03o") for b in data)
        bash.append(f'printf -v {key} %b "{octets}"')
        b64 = base64.b64encode(data).decode("ascii")
        posix.append(f'{key}="$(printf %s {b64} | /usr/bin/base64 -d)"')
    setup = ('if [ -n "${BASH_VERSION-}" ] && command -p -v shopt >/dev/null 2>&1; then '
             + "; ".join(bash) + "; else " + "; ".join(posix) + "; fi; ")
    return command.replace("export LC_ALL=C; ", "export LC_ALL=C; " + setup, 1)


def installed_files(host, dest, python):
    files = {name: (ROOT / name).read_bytes() for name in ("LICENSE", *PAYLOADS[host])}
    if host == "claude":
        template = read_object((ROOT / "hooks/hooks.json").read_bytes())
        for groups in template["hooks"].values():
            for group in groups:
                for handler in group["hooks"]:
                    handler["command"] = claude_command(handler["command"], dest, python)
        files["hooks/hooks.json"] = json_bytes(template)
        files["hooks/python.sh"] = (ROOT / "hooks/python.sh").read_bytes()
        return files, template["hooks"]
    if host == "codex" and ON_WINDOWS:
        # A session can dispatch this declaration through cmd or PowerShell.
        command = (unquoted_windows_path(WINDOWS_SHELL) +
                   " -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " +
                   quoted_path(dest / "scripts/codex_ps_publish_hook.ps1", powershell=True) +
                   " -PythonPath " + quoted_path(python, powershell=True))
    elif host == "antigravity" and ON_WINDOWS:
        interpreter = unquoted_windows_path(
            python, "The Python interpreter path requires an unquoted spelling. Run this installer with "
                    "Python 3.11+ at a path without spaces or shell metacharacters, or with a usable 8.3 name.")
        # Only the profile needs to exist. The fixed config and package names
        # can be appended before any part of the installation is created.
        home = Path.home()
        profile = unquoted_windows_path(
            home, "Antigravity uses a fixed settings directory under the Windows profile. Ask an administrator "
                  "for a usable 8.3 name for the profile path, or use an account whose profile path has no "
                  "spaces or shell metacharacters.")
        adapter = (Path(profile) / dest.relative_to(home) / "scripts/antigravity_backtick_guard.py").as_posix()
        command = f"{interpreter} -I -X utf8 -B {adapter} 2>nul || exit /b 0"
    else:
        filename = "codex_posix_hook.py" if host == "codex" else "antigravity_backtick_guard.py"
        command = shlex.join([str(python), "-I", "-X", "utf8", "-B", str(dest / "scripts" / filename)])
        if host == "antigravity":
            command += " --shell=bash 2>/dev/null || exit 0"
    matcher, timeout = ("^Bash$", 30) if host == "codex" else ("run_command|manage_task", 15)
    return files, {"PreToolUse": [{"matcher": matcher, "hooks": [
        {"type": "command", "command": command, "timeout": timeout}]}]}


def registrations(config, host):
    key = NAME if host == "antigravity" else "hooks"
    table = config.setdefault(key, {})
    if not isinstance(table, dict):
        raise InstallError("The host hook table must be a JSON object.")
    return table


def remove_owned(table, owned):
    for event, groups in owned.items():
        rows = table.get(event, [])
        if not isinstance(rows, list):
            raise InstallError("Invalid event declaration.")
        for group in groups:
            handler, = group["hooks"]
            matches = [row for row in rows if isinstance(row, dict) and row.get("matcher") == group["matcher"]
                       and isinstance(row.get("hooks"), list) and handler in row["hooks"]]
            if len(matches) != 1 or matches[0]["hooks"].count(handler) != 1:
                raise InstallError("A registered hook was removed, duplicated or edited; inspect the declaration.")
            row = matches[0]
            row["hooks"].remove(handler)
            if not row["hooks"] and set(row) == {"matcher", "hooks"}:
                rows.remove(row)


def add_owned(table, owned):
    for event, groups in owned.items():
        rows = table.setdefault(event, [])
        if not isinstance(rows, list):
            raise InstallError("Invalid event declaration.")
        for group in groups:
            handler, = group["hooks"]
            if any(isinstance(row, dict) and row.get("matcher") == group["matcher"] and
                   handler in (row.get("hooks") or []) for row in rows):
                raise InstallError("An existing registration already contains this hook.")
            rows.append(copy.deepcopy(group))


def load_state(dest, host):
    if not dest.exists() and not dest.is_symlink():
        return None
    if dest.is_symlink() or not dest.is_dir() or not (dest / MARKER).is_file():
        raise InstallError("An unowned or linked installation directory is present.")
    state = read_object((dest / MARKER).read_bytes())
    if state.get("format") != 1 or state.get("host") != host:
        raise InstallError("Unrecognized installation receipt.")
    return state


def check_files(dest, state, expected_names):
    permitted = set(expected_names) | {MARKER}
    expected_dirs = {p.parent for p in map(Path, permitted)} - {Path(".")}
    found = set()
    for path in dest.rglob("*"):
        rel = path.relative_to(dest)
        if path.is_symlink() or (path.is_dir() and rel not in expected_dirs):
            raise InstallError("Installation contains an unexpected directory or link.")
        if path.is_file():
            found.add(rel.as_posix())
    if found != permitted or set(state["files"]) != set(expected_names):
        raise InstallError("Installed file set has changed.")
    if any(digest((dest / name).read_bytes()) != value for name, value in state["files"].items()):
        raise InstallError("Installed file contents have changed.")


@contextmanager
def editing(directory):
    lock = directory / ("." + NAME + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise InstallError("An install lock exists. Check for a running installer before removing the lock.") from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def change(host, action):
    if action == "install" and sys.version_info[:2] < MIN_PYTHON:
        raise InstallError(PYTHON_REQUIREMENT)
    if action == "install" and host == "claude":
        claude_shell()
    cfg = location(host)
    dest = cfg.parent / NAME
    if action == "install":
        python = Path(sys.executable).resolve() if ON_WINDOWS else Path(sys.executable).absolute()
        files, entries = installed_files(host, dest, python)
    elif not cfg.parent.exists():
        return
    cfg.parent.mkdir(parents=True, exist_ok=True)
    with editing(cfg.parent):
        raw = read_config(cfg)
        config = read_object(raw) if raw is not None else {}
        old = load_state(dest, host)
        if not old and action == "uninstall":
            table = json.dumps(config.get("hooks", {}), ensure_ascii=False)
            encoded = base64.b64encode(dest.as_posix().encode("utf-8")).decode("ascii")
            normalized = table.replace("\\\\", "/").casefold()
            refers_to_package = dest.as_posix().casefold() + "/" in normalized or encoded in table
            if (host == "antigravity" and NAME in config) or (host != "antigravity" and refers_to_package):
                raise InstallError(f"A hook registration remains in {cfg.name} without its installation "
                                   "receipt. Inspect the declaration and remove the stale entry before reinstalling.")
            return
        key = NAME if host == "antigravity" else "hooks"
        if not old and host == "antigravity" and key in config:
            raise InstallError("The named hook table already belongs to another installation.")
        had_table = key in config
        table = registrations(config, host)
        if old:
            check_files(dest, old, old["files"])
            if raw is not None or action == "install":
                remove_owned(table, old["entries"])
        empty_before = old["events_before"] if old else list(table)
        had_table = old["table_before"] if old else had_table
        had_config = old["config_before"] if old else raw is not None
        if action == "install":
            hashes = {name: digest(data) for name, data in files.items()}
            new = {"format": 1, "host": host, "entries": entries, "files": hashes, "python": str(python),
                   "config_before": had_config, "table_before": had_table, "events_before": empty_before}
            if old and "last_probe" in old:
                new["last_probe"] = old["last_probe"]
            add_owned(table, entries)
            if new == old:
                return
        elif raw is not None:
            for event in old["entries"]:
                if not table[event] and event not in empty_before:
                    del table[event]
            if not table and not had_table:
                del config[key]
        with tempfile.TemporaryDirectory(prefix="." + NAME + "-", dir=cfg.parent) as tmp:
            tmp = Path(tmp)
            stage, previous = tmp / "new", tmp / "old"
            if action == "install":
                for name, data in {**files, MARKER: json_bytes(new)}.items():
                    target = stage / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            replacement = tmp / "settings"
            replacement.write_bytes(json_bytes(config))
            if cfg.exists():
                shutil.copymode(cfg, replacement)
            else:
                replacement.chmod(0o600)
            if read_config(cfg) != raw:
                raise InstallError("Configuration changed during installation; retry.")
            if old:
                os.replace(dest, previous)
            try:
                if action == "install":
                    os.replace(stage, dest)
                if action == "uninstall" and (raw is None or (not config and not had_config)):
                    cfg.unlink(missing_ok=True)
                else:
                    os.replace(replacement, cfg)
            except BaseException:
                if action == "install" and dest.exists():
                    os.replace(dest, stage)
                if old:
                    os.replace(previous, dest)
                raise


def bash_executable():
    if ON_WINDOWS:
        for root in (os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles")):
            if root and (Path(root) / "Git/bin/bash.exe").is_file():
                return str(Path(root) / "Git/bin/bash.exe")
    for directory in os.get_exec_path():
        path = Path(directory)
        if not path.is_absolute() or path.resolve() == Path.cwd().resolve():
            continue
        if ON_WINDOWS and any(part.lower() in ("system32", "windowsapps") for part in path.parts):
            continue
        binary = path / ("bash.exe" if ON_WINDOWS else "bash")
        if binary.is_file() and os.access(binary, os.X_OK):
            return str(binary)
    raise InstallError("Git Bash or Bash was not found.")


def claude_shell():
    if ON_WINDOWS:
        # Isolated Python does not import modules from the package directory.
        finder = runpy.run_path(str(ROOT / "scripts/bash_quote_guard.py"))["_self_test_shell"]
        shell = finder()
        if not shell:
            raise InstallError("Claude Code hooks on Windows require Git Bash. Install Git for Windows first.")
        return shell
    if not all(os.access(path, os.X_OK) and Path(path).is_file() for path in ("/bin/sh", "/bin/bash")):
        raise InstallError("Claude Code hooks require /bin/sh and /bin/bash.")
    return "/bin/sh"


def synthetic_reply(host, event, deny, cmd, cwd):
    result = subprocess.run(cmd, input=json_bytes(event), capture_output=True, cwd=cwd, timeout=14)
    if host == "claude":
        return (result.returncode == (2 if deny else 0)
                and (not deny or b"[backtick-check-hook]" in result.stderr))
    if result.returncode != 0 or not deny:
        return result.returncode == 0 and not result.stdout.strip()
    body = read_object(result.stdout)
    if host == "codex":
        body = body.get("hookSpecificOutput", {})
        decision, reason = body.get("permissionDecision"), body.get("permissionDecisionReason", "")
    else:
        decision, reason = body.get("decision"), body.get("reason", "")
    return decision == "deny" and "[backtick-check-hook]" in reason


def synthetic(host, entries, cwd):
    bash_probe = 'echo "sample ' + chr(96) + 'x' + chr(96) + '"'
    ps_probe = 'if ($false) { gh release create demo --notes "sample ' + chr(96) + 'x' + chr(96) + '" }'
    for group in entries["PreToolUse"]:
        claude = host == "claude"
        is_bash = group["matcher"] == "Bash|Monitor" if claude else not ON_WINDOWS
        tools = group["matcher"].split("|") if claude else (["Bash"] if host == "codex"
                                                           else ["run_command", "manage_task"])
        line = group["hooks"][0]["command"]
        if claude or not ON_WINDOWS:
            runners = [
                [claude_shell() if claude else bash_executable(), "-c", line],
            ]
        else:
            cmd = str(WINDOWS_SHELL.parents[2] / "cmd.exe")
            runners = ['"' + cmd + '" /C "' + line + '"']
            if host == "codex":
                runners.append([str(WINDOWS_SHELL), "-NoProfile", "-Command", line])
            else:
                runners.append([cmd, "/C", line])
        allowed = "echo plain" if is_bash else 'Write-Output "a' + chr(96) + 'tb"'
        for tool in tools:
            for deny, sample in [(True, bash_probe if is_bash else ps_probe), (False, allowed)]:
                if host == "antigravity":
                    args = {"Input": sample, "Action": "send_input"} if tool == "manage_task" else {"CommandLine": sample}
                    event = {"hookEventName": "PreToolUse", "toolCall": {"name": tool, "args": args}}
                else:
                    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": sample}}
                if not all(synthetic_reply(host, event, deny, cmd, cwd) for cmd in runners):
                    return False
    return True


def host_version(host):
    if host == "antigravity":
        p = Path.home() / ".gemini/bin/agy.version.json"
        if p.is_file():
            return read_object(p.read_bytes()).get("version")
    return None


def display_path(path):
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return path.name


def version_string(text):
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+_-]{0,79}", text):
        raise argparse.ArgumentTypeError("expected a host version number")
    return text


def examine(host, selected_version, record=False):
    cfg = location(host)
    dest = cfg.parent / NAME
    warnings = []
    version = selected_version or host_version(host)
    result = {"host": host, "configuration": display_path(cfg), "synthetic": "not-run", "host_probe": "unrecorded",
              "host_version": version, "version_source": "operator-running-host" if selected_version else
              ("on-disk" if version else "unknown"), "version_drift": None,
              "last_probe_version": None, "trust": "review /hooks in the running CLI or Review hooks in the desktop app" if host == "codex"
              else "not-applicable", "warnings": warnings}
    if sys.version_info[:2] < MIN_PYTHON:
        warnings.append(PYTHON_REQUIREMENT)
        return result, 1
    if host == "codex":
        warnings.append("Trust review required after registration or a declaration change. Open /hooks in the CLI "
                        "or Settings > Hooks in the desktop app, then probe the running session.")
    if host == "antigravity" and ON_WINDOWS:
        warnings.append("The running host's cmd dispatch mode is unmeasured. Synthetic probes cover raw and argument-list dispatch.")
    if host == "claude":
        try:
            claude_shell()
        except InstallError as exc:
            warnings.append(str(exc))
            return result, 1
    elif not ON_WINDOWS:
        warnings.append("POSIX host shell selection is unmeasured. Routing uses Bash.")
    if not result["host_version"]:
        warnings.append("Running host version unknown. Supply --host-version from that host.")
    elif not selected_version:
        warnings.append("On-disk version only. Supply the running host version after a restart or upgrade.")
    state = load_state(dest, host)
    if not state:
        warnings.append("Registration not installed.")
        return result, 1
    python = Path(state["python"])
    files, expected = installed_files(host, dest, python)
    try:
        if state["entries"] != expected or not python.is_absolute():
            raise InstallError("Installed declaration differs from this package.")
        check_files(dest, state, files)
        if state["files"] != {name: digest(data) for name, data in files.items()}:
            raise InstallError("Installed version differs from this package.")
        config = read_object(read_config(cfg) or b"{}")
        remove_owned(registrations(config, host), expected)
        version = subprocess.run([str(python), "-I", "-X", "utf8", "-B", "--version"],
                                 capture_output=True, check=True, timeout=5)
        result["python"] = {"executable": display_path(python),
                            "version": (version.stdout or version.stderr).decode("ascii").strip()}
        major_minor = re.match(r"Python (\d+)\.(\d+)", result["python"]["version"])
        if not major_minor or tuple(map(int, major_minor.groups())) < MIN_PYTHON:
            warnings.append("Registered interpreter: " + PYTHON_REQUIREMENT)
            return result, 1
        result["synthetic"] = "passed" if synthetic(host, expected, dest) else "failed"
    except (OSError, ValueError, InstallError, subprocess.SubprocessError):
        warnings.append("Check hook registration, installed files and interpreter availability.")
        result["synthetic"] = "failed"
    fingerprint = digest(json_bytes(state["files"]))
    if record and result["synthetic"] == "passed":
        state["last_probe"] = {"version": selected_version, "files": fingerprint}
        with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(json_bytes(state))
        try:
            os.replace(tmp, dest / MARKER)
        finally:
            tmp.unlink(missing_ok=True)
    probe = state.get("last_probe", {})
    result["files_sha256"] = fingerprint
    result["declarations_sha256"] = digest(json_bytes(expected))
    result["last_probe_version"] = probe.get("version")
    if not probe:
        warnings.append("Host probes unrecorded. Run the three probes in a fresh host session.")
    else:
        result["host_probe"] = "operator-recorded"
        if result["host_version"]:
            result["version_drift"] = result["host_version"] != probe["version"]
        if result["version_drift"] or fingerprint != probe["files"]:
            result["host_probe"] = "stale"
            warnings.append("Version or installed hook changed since the user-recorded host probe.")
    return result, 0 if result["synthetic"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall", "doctor", "record-probe"])
    parser.add_argument("--host", required=True, choices=PAYLOADS)
    parser.add_argument("--host-version", type=version_string, help="version shown by the running host")
    args = parser.parse_args()
    try:
        if args.action in ("install", "uninstall"):
            change(args.host, args.action)
            print(args.action, args.host, "OK")
            return 0
        if args.action == "record-probe":
            if not args.host_version:
                parser.error("record-probe requires --host-version after a successful manual host probe")
            cfg = location(args.host)
            if not cfg.parent.is_dir():
                raise InstallError("Install the hook before recording a probe.")
            with editing(cfg.parent):
                result, code = examine(args.host, args.host_version, record=True)
        else:
            result, code = examine(args.host, args.host_version)
        print(json.dumps(result, ensure_ascii=True))
        return code
    except (OSError, ValueError, KeyError, TypeError, RecursionError, InstallError, subprocess.SubprocessError) as exc:
        # Configuration files may contain unrelated private settings.
        print(str(exc) if isinstance(exc, InstallError) else type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
