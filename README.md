# Backtick Check Hook

Keep literal Markdown and command text intact when a coding assistant calls a shell. The Bash checker looks for backticks in command-substitution positions. The PowerShell checker looks for active backticks in commands that also write text with Git or the GitHub CLI. A normal PowerShell tab escape in an output command passes.

[한국어 안내](README.ko.md) · [Security and trust](SECURITY.md) · [Changes](CHANGELOG.md)

## Install and check

Use a trusted copy of the package and a user-controlled Python 3.10+ installation. From the package root, choose the host you use. For example, to register the Windows Codex hook:

~~~powershell
python -I -X utf8 -B install.py install --host codex
python -I -X utf8 -B install.py doctor --host codex
~~~

Use **claude**, **codex**, or **antigravity** as the host name. On Windows with the Python launcher, substitute **py -3** for **python**. On POSIX, use **python3**. The installer pins the interpreter that runs it. It copies that host's files and license to a **backtick-check-hook** directory beside the user's configuration, and registers the relevant handlers. Install and uninstall check the registration and installed files for conflicting edits. Keep a copy of your config if you need to restore its exact formatting.

| Host | Registration and verdict | After installation |
|---|---|---|
| Claude Code | User settings, or the package's native plugin manifest. Bash and Monitor use the Bash checker, PowerShell uses the publishing checker. Git Bash invokes the prefilter on Windows. Checker exit 42 maps to hook exit 2. Other checker exits allow execution. | Use one registration method. Start a new session. SessionStart runs the installed Bash hook with synthetic events. The inner self-test returns 10 when healthy. The outer hook reports a warning when needed and exits 0. |
| Codex | The installer writes a user PreToolUse declaration for the Bash tool name. On Windows the adapter runs under Windows PowerShell. A deny response is JSON with process exit 0. The host timeout is 30 seconds. | Trust the declaration in the running client's **/hooks** screen. If trust was recorded by a different process, restart Codex or reload the VS Code window. Probe a new conversation and a child created in it. A separate hooks/list query reports the querying process's state. |
| Antigravity | A named entry in the user's hooks.json covers **run_command** and **manage_task** input delivery. Windows uses cmd /c to start the adapter. A deny is JSON. Passing produces empty stdout and exit 0. The Windows wrapper handles launcher failure with exit 0. | Start a new conversation. Restart the hub yourself to refresh existing conversations and probe again after an update. Duplicate registrations can run twice. |

Claude Code can also load the package root as a plugin with **claude --plugin-dir** followed by its absolute path. Use a trusted installation directory outside editable projects. Global user registration is the installer default. Project-local hooks can be changed by whoever controls that project. On POSIX the Codex and Antigravity declarations select Bash. Actual host shell selection on Linux and macOS is **unmeasured**. On Windows a requested shell hint can differ from the process that actually executes the command. These two adapters use the Windows PowerShell checker.

**Doctor** checks registration, interpreter availability, installed file digests and synthetic events. A passing result concerns the installed command. To associate a successful manual probe with a running host version, use **record-probe --host HOST --host-version VERSION** after running the probes below. Supply the version from the running host to **doctor --host-version VERSION** on later checks. Disk and running versions can differ. Review the Codex declaration after changing it. Its trust hash covers the declaration. Review adapter and checker changes as well.

The installer uses user hook declarations for Codex and Antigravity. Codex's native plugin trust can also cover bundled script changes. Antigravity's native plugin layout supports a root hooks.json with paths relative to its plugin root. This installer registers absolute installed paths. [Codex hook trust](https://developers.openai.com/codex/hooks/) · [Antigravity plugin layout](https://antigravity.google/docs/build-plugins.md)

## Probe your host

Send each line as its own shell tool call. In Windows PowerShell, use:

~~~powershell
if ($false) { gh release create v0.0.0-probe --notes "probe `x` text" }
Write-Output "a`tb"
echo plain
~~~

The first line should stop before the shell and give the **[backtick-check-hook]** marker at positions 1:61 and 1:63. The next two should return exit 0, with a tab between a and b, then the word plain. The false branch keeps the release command inactive. If another hook blocks first, attribution is inconclusive. For Bash, use the following three calls. The first should be blocked with the same package marker, the second and third should print their literal text:

~~~bash
if false; then echo "probe `x` text"; fi
echo 'literal `x`'
echo plain
~~~

### Live host measurements

| Host | Running version | Mode | OS | Execution shell | Date / candidate commit | Result |
|---|---|---|---|---|---|---|
| Claude Code | — | — | — | — | — | Untested |
| Codex | — | — | — | — | — | Untested |
| Antigravity | — | — | — | — | — | Untested |

This table records a result when a live session has loaded and exercised the candidate package. Local adapter tests use controlled event payloads. Earlier observations of empty output and an empty JSON object's behavior used Antigravity CLI 1.5.17 in its review/automatic modes with a previous adapter. Empty output is an observed convention. Timeout behavior in Antigravity is unmeasured. Codex child configuration inheritance is established by its source. A comparison across a server restart changes several variables at once.

## Limits and false positives

- **Bash syntax.** Single quotes, ANSI-C quoted strings, quoted heredocs, comments and a single escaped backtick normally protect literal text. The default allows dollar-parenthesis substitutions. The optional strict checker mode recognizes some mixed-text substitutions. Bash scripts inside separately quoted shell or SSH arguments, and variable expansion that silently changes text, fall outside this check.
- **Conservative Bash parsing.** The checker considers the raw command and a form with folded backslashes. On Windows it also accounts for Git Bash dropping carriage returns. A launcher with different quoting behavior can produce unnecessary blocks. Array subscripts can depend on the variable's runtime type. Incomplete heredocs can make subsequent text ambiguous. The parser stops at a depth of 150 or its three-second scan budget and uses the findings so far. SessionStart checks the declared Bash and Monitor handlers at startup, resume, clear, compact or fork. It cannot continuously detect host-wide disabling, changes between those events, or a silent host that never starts the hook.
- **PowerShell scope.** Recognition covers common text-writing forms of gh release, pr, issue and api, and git commit, tag, notes and merge. Earlier writes to a body file, commands in a script file, splatted or variable-built arguments, dynamic commands, Start-Process, encoded commands and constructed script blocks fall outside reliable coverage. Other writing commands such as gh repo edit --description, gh secret set --body, git stash -m or git commit-tree are outside the recognized set. A different shell started inside the current shell, interactive Codex write_stdin, and Antigravity input sent to a different kind of shell also require separate review.
- **PowerShell grammar and bounds.** Comments between command words, comments following expressions that contain a quote, a block-comment opener immediately after a dollar sign, parenthesized option values, an implicit or line-split -Command, and more than three levels of indirect evaluation can change recognition. Attached or abbreviated tag/merge message options may be missed. The recognizer has a 32-option Git prefix bound and a 4,000-character search after certain verbs. A command containing a backtick and a recognized publishing operation can be conservatively refused if it exceeds 400,000 characters or parsing is incomplete.
- **Whole-command matches.** A publishing verb in a comment or quoted example, an indirect evaluation elsewhere, an unrelated escape alongside a file-based commit, or an amend with --no-edit can trigger a block. An expression-adjacent comment or text following the PowerShell stop-parsing token may be read as ordinary arguments. A read-only gh api call followed by a PowerShell switch such as -First, -Force, -Filter or -FilePath can look like a field write. Read-only git tag or notes can match words or switches in another statement. This release preserves those decisions. Split unrelated operations and create publication text with a file-writing tool before passing the file by name.
- **Errors and cost.** Missing or untrusted handlers, a missing interpreter, malformed events and processing failures can leave a command unchecked. Codex can proceed after its timeout. Claude and Antigravity declarations use 15 seconds for PreToolUse. The Claude fast path avoids Python when the raw event has no backtick marker. The Windows Codex route starts PowerShell for shell calls. The Antigravity route starts its Python adapter. Python before 3.11 uses an alternative regex implementation that can be slower on repeated continuations.

### Local launcher timings

**Python 3.10 compatibility issue.** The unchanged PowerShell timing regression for repeated CRLF continuations exceeds its original 0.5-second limit with the Python 3.10 regex fallback. In the Windows suite each original speed test on 3.10 has an additional eight-second subprocess deadline. An overrun is a failure, and the suite continues. Use Python 3.11 or newer for the candidate.

On Windows, warm seven-call medians for a plain event fell below 0.5 s for the Git Bash prefilter and the cmd/Python adapter, and between 0.2 s and 2 s for the cmd/PowerShell adapter. These are synthetic launch-to-exit intervals under local load. The comparison invokes each configured handler from a temporary home and times an empty invocation of the same outer shell separately. Subtract the empty-shell median when estimating the added cost. Interactive host latency is unmeasured. A shared Python adapter would also start Python on the Windows Codex plain-command path and would still need different host response formats.

## Remove or troubleshoot

Run **python install.py uninstall --host HOST** for the installation you created. The installer checks its receipt before removing owned files and handlers. If a malformed Claude shell hook prevents shell calls, use the plugin screen or a text editor to disable its registration, then start a new session. A broken Bourne-shell hook may itself exit 2, which Claude interprets as a denial. A separately registered plugin or project hook remains active until its owner removes it.

Run the Windows suite in independent consoles with **python -B tools/test_windows.py 65001** and **python -B tools/test_windows.py 949**. The suite uses temporary homes, installed commands and a Git Bash reference for Bash 5.3 syntax. A suitable Git Bash and PowerShell 7 are needed for their respective coverage; Windows PowerShell 5.1 is tested separately. For authoring release notes or commit messages, write the content with a file editor and pass **--notes-file**, **--body-file** or **git commit -F** as appropriate.
