# Backtick Check Hook

A backtick can change a Markdown example as a coding assistant passes it through a shell. This hook checks for Bash command substitution and for active PowerShell backticks in Git or GitHub CLI commands that write text. A PowerShell tab escape in an ordinary output command passes.

[한국어 안내](README.ko.md) · [Security and trust](SECURITY.md) · [Changes](CHANGELOG.md)

## Install and check

Use a trusted copy of the package and a user-controlled **Python 3.11 or newer**. The installer rejects Python 3.10 and earlier. From the package root, choose your host. For example, these commands register and check the Codex hook on Windows.

~~~powershell
python -I -X utf8 -B install.py install --host codex
python -I -X utf8 -B install.py doctor --host codex
~~~

Use `claude`, `codex` or `antigravity` for `--host`. With the Windows Python launcher, replace `python` with `py -3`. On POSIX use `python3`. The installer registers the interpreter used to run it, copies the host's files and the license into a `backtick-check-hook` directory beside the user's configuration, and registers the handlers there. Installation and removal check for conflicting edits. Keep a copy of your configuration if you need to restore its exact formatting.

| Host | Registration and verdict | After installation |
|---|---|---|
| Claude Code | **Windows requires Git Bash for this hook.** Installation refuses to register it when Git Bash is missing. On POSIX, the host's `sh -c` starts `/bin/bash` by absolute path. Bash and Monitor use the Bash checker, PowerShell uses the publishing checker. On these supported paths, checker exit 42 yields hook exit 2 (deny), and the wrapper maps other checker exits to 0. | Choose either user settings or the native plugin. Start a new session and run the probes below. At SessionStart the user installation tests the handler registered in `settings.json` and the native plugin tests its own `hooks/hooks.json`. The self-test returns 10 when healthy. Its wrapper reports a failed self-test or missing launcher, then exits 0. |
| Codex | A user PreToolUse hook matches the tool name `Bash`. On Windows the adapter runs in Windows PowerShell. A denial returns JSON and exit 0. The host timeout is 30 seconds. | Trust the declaration in the running client. In the CLI open `/hooks`. In the desktop app select **Review hooks** or **Settings → Hooks**. If a separate process recorded trust, restart Codex or reload the VS Code window. Run the probes in a new conversation and a child created in it. A separate `hooks/list` query reports the querying process's state. |
| Antigravity | A named entry in the user's `hooks.json` handles `run_command` and `manage_task` input delivery. Windows CLI 1.5.17 was observed to use `cmd /c` and to accept empty stdout with exit 0 as a pass. The adapter returns JSON to deny. The Windows wrapper exits 0 on launcher failure. | Start a new conversation. To refresh existing conversations, restart the hub. Repeat the probes after updates. Duplicate registrations can run twice. |

For registration across sessions, use the installer. It writes only to user-level registrations. For a single Claude Code session, `claude --plugin-dir` followed by the absolute package path loads the native plugin. On Windows this also requires Git Bash. Both Claude routes on POSIX require `/bin/sh` and `/bin/bash`. Use a trusted directory outside editable projects. Anyone who can change a project's files can change its project-local hooks. On Windows the Codex and Antigravity registrations select the PowerShell checker even when a request includes a different shell hint. On POSIX those registrations select the Bash checker. Actual shell selection in live Linux and macOS sessions is unmeasured.

`doctor` checks registration, interpreter availability, installed file hashes and synthetic events. It warns if Python is below 3.11. A passing result concerns the installed command. Run the probes in a fresh host session, then use `record-probe --host HOST --host-version VERSION` to record the running host version. On later checks pass it to `doctor --host HOST --host-version VERSION`. Disk and running versions can differ. Codex's trust hash covers the declaration. Review any change to the declaration, adapter or checker and renew trust after editing the declaration.

Claude's PreToolUse declarations set `onFailure` to `continue` for hook execution errors. An intentional exit 2 still denies the call. This option requires Claude Code 2.1.295 or newer. In offline strict validation, 2.1.248 and 2.1.252 accepted both this value and an invalid value. Version 2.1.330 rejected the invalid value. Live handling on older versions is unverified. [Claude Code hook reference](https://code.claude.com/docs/en/hooks)

Codex and Antigravity use user hook declarations in this installation. Native Codex plugin trust can also cover bundled script changes. Native Antigravity plugins support a root `hooks.json` and paths relative to that root. This installer registers absolute installed paths. [Codex hook trust](https://developers.openai.com/codex/hooks/) · [Antigravity plugin layout](https://antigravity.google/docs/build-plugins.md)

## Probe your host

On Windows, `doctor` exercises the installed Codex command under both cmd and PowerShell. Spaces and non-ASCII characters are supported in the adapter and interpreter paths. The installer rejects path characters it cannot quote for both dispatchers, including percent, exclamation, dollar and backtick characters. For Antigravity, the installer uses an unquoted, shell-safe absolute path or a Windows 8.3 short name for the same file. If neither is available it refuses installation. The Antigravity check exercises cmd with a raw command line and with an argument list. The live host's argument-passing convention is unmeasured.

Send each line as its own shell tool call. For the Claude PowerShell tool or Windows Codex and Antigravity PowerShell routes, use the following commands.

~~~powershell
if ($false) { gh release create v0.0.0-probe --notes "probe `x` text" }
Write-Output "a`tb"
echo plain
~~~

The first call should stop before the shell runs. Look for **[backtick-check-hook]** anywhere in the message and the reported positions 1:61 and 1:63. The false branch keeps the release command inactive. The next two calls should return exit 0 and print a tab between a and b, then the word `plain`. If another hook blocks first, attribution is inconclusive.

Use the Bash probes below only for Claude's Bash or Monitor tool or the POSIX Codex and Antigravity registrations. The first call should be blocked with the same marker. The other two should print their literal text.

~~~bash
if false; then echo "probe `x` text"; fi
echo 'literal `x`'
echo plain
~~~

### Live host measurements

| Host | Running version | Mode | OS | Execution shell | Date / commit | Result |
|---|---|---|---|---|---|---|
| Claude Code | — | — | — | — | — | Untested |
| Codex | — | — | — | — | — | Untested |
| Antigravity | — | — | — | — | — | Untested |

The table covers version 0.1.0 in live host sessions. Local adapter tests use synthetic events. Antigravity's hook protocol lists `decision` as required. Empty output was accepted as a pass in CLI 1.5.17 in review and automatic modes. How the host handles its own timeout is unmeasured. [Antigravity hooks](https://antigravity.google/docs/hooks.md)

## Limits and false positives

- **Bash syntax.** The checker approximates Bash quoting and can miss rare constructs. Single quotes, ANSI-C quoted strings, quoted heredocs, comments and a single escaped backtick normally preserve literal text. The shipped hooks allow dollar-parenthesis substitutions. Only the checker CLI's `--strict` option checks some mixed-text substitutions. Scripts inside separately quoted shell or SSH arguments, and variable expansion that silently changes text, fall outside this check.
- **Bash parsing limits.** The checker reads the raw command and a form with folded backslashes. On Windows it also accounts for Git Bash dropping carriage returns. A launcher with different quoting behavior can produce unnecessary blocks. Array subscripts can depend on the variable's runtime type. Incomplete heredocs can make later text ambiguous. At depth 150 or the three-second scan budget, the parser uses the findings so far. SessionStart checks Bash and Monitor at startup, resume, clear, compact and fork. A hook that never starts or is changed between checks can go undetected. SessionStart warnings are not visible to subagents.
- **PowerShell scope.** The checker recognizes common text-writing forms of gh release, pr, issue and api, and git commit, tag, notes and merge. Earlier writes to a body file, commands in a script file, splatted or variable-built arguments, dynamic commands, Start-Process, encoded commands and generated script blocks can escape recognition. Examples outside the recognized set include gh repo edit --description, gh secret set --body, git stash -m and git commit-tree. If one shell starts another, the checker may parse for the wrong shell. Codex `write_stdin` input bypasses PreToolUse and receives no check. Some specialized Codex tool paths can also skip PreToolUse. Antigravity compares tool and argument names literally, including case. An unrecognized spelling receives no check. Input sent to a different kind of shell can be interpreted differently. [Codex hook coverage](https://developers.openai.com/codex/hooks/)
- **PowerShell grammar and bounds.** Recognition can miss comments between command words, a single quote inside a comment immediately following an expression, a block-comment opener after a dollar sign, parenthesized option values, an implicit or line-split -Command, and indirect evaluation beyond three levels. Attached or abbreviated tag/merge message options can also be missed. Git prefixes are limited to 32 options and searches after certain verbs to 4,000 characters. The checker may refuse a command containing a backtick and a recognized publishing operation if it exceeds 400,000 characters or parsing is incomplete.
- **Whole-command matches.** A publishing verb in a comment or quoted example, an indirect evaluation elsewhere, an unrelated escape alongside a file-based commit, or an amend with --no-edit can trigger a block. An expression-adjacent comment or text after the PowerShell stop-parsing token may be read as ordinary arguments. Read-only gh api followed by -First, -Force, -Filter or -FilePath can look like a field write. Read-only git tag or notes can match words or switches in another statement. Separate unrelated operations and write publication text to a file before passing its name to Git or the GitHub CLI.
- **Errors and timeouts.** A missing or untrusted hook, a missing interpreter, malformed input or a processing error can leave a command unchecked. Codex can proceed after its 30-second host timeout. Claude Code can proceed unchecked after its 15-second PreToolUse timeout. Antigravity's adapter returns empty output if the checker exceeds 10 seconds, so a command can proceed unchecked. Its host declaration requests 15 seconds. On Windows a Git Bash hook's child process can outlive a timed-out wrapper. [Claude Code hook timeouts](https://code.claude.com/docs/en/hooks)

### Python version and local launcher timings

**Why Python 3.11 is required.** Python 3.10 lacks possessive regex quantifiers. Its fallback uses ordinary quantifiers, so the PowerShell checker's runtime can grow exponentially with repeated CRLF continuations. A Python 3.10.11 measurement took 3.3 seconds for 20 continuations and 12.3 seconds for 22. If the checker reaches the hook's timeout the command can proceed unchecked. Use Python 3.11 or newer.

For a Windows reference measurement, commit `bf18baf9` was run on 2026-11-26 (KST) with Windows 11 Insider build 26300.9974, Python 3.12.10, Git Bash 5.3.15 and Windows PowerShell 5.1.26100.9818. After one warm-up, the median of seven plain events was 189 ms for the Git Bash prefilter, 596 ms for cmd/PowerShell and 171 ms for cmd/Python. Subtracting the median startup cost of each empty outer shell gave about 15, 527 and 103 ms, respectively. These synthetic timings cover launch to exit from temporary user settings at that commit. Live session latency for version 0.1.0 is unmeasured. Claude's prefilter skips Python on events without a backtick marker. Windows Codex starts PowerShell for shell calls, and Antigravity starts its Python adapter.

## Remove, troubleshoot and test

Run `python -I -X utf8 -B install.py uninstall --host HOST` for the host you installed. The installer checks its installation record before removing owned files and handlers. If the package directory is already gone and registration remains, inspect the host configuration and remove the stale hook before reinstalling. If a malformed Claude hook blocks shell calls, disable the registration in the plugin screen or a text editor, then start a new session. A shell syntax error can itself produce exit 2, which Claude treats as a denial. Separately registered plugins and project hooks have their own registrations.

On Windows run `python -B tools/test_windows.py 65001` and `python -B tools/test_windows.py 949`. Each command starts a separate console and runs the tests in temporary homes. Install Git Bash and PowerShell 7 for their respective tests. Windows PowerShell 5.1 is checked separately. The suite compares Bash 5.3 syntax with Git Bash. `BACKTICK_TIMING_SCALE` multiplies the absolute timing assertions (0.1, 0.5, 1.0 and 2.0 seconds). Use a positive finite number. The default is 1 and CI uses 3. The multiplier applies only to the test thresholds. When writing release notes and commit messages, create the text in a file editor and pass the file with `--notes-file`, `--body-file` or `git commit -F`.
