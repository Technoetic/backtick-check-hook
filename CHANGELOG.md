# Changelog

## 0.2.0

- Narrowed PowerShell publishing checks to the publishing statement and same-command variables or subexpressions referenced by its inline arguments, eliminating false positives from unrelated escapes in separate statements (such as `` "`t" `` or `` Select-String -Pattern "`r" `` alongside single-quoted notes).
- Excluded text-free commit forms (`git commit --no-edit`, `--amend --no-edit`, `-C`, `--reuse-message` when no `-m`/`-F`/`-e`/`-t` or upstream pipe is present), statement-local read-only `git tag`/`notes`/`merge` and `gh api` calls, and passive publishing verbs appearing solely inside non-evaluated string literals or comments.
- Preserved conservative whole-command blocking for file/stdin/pipe publishing (`-F`, `--notes-file`, `--body-file`, `--input`, `-t`, upstream `|`), splatting (`@var`), pipeline/parameter variables (`$_`, `$PSItem`, `$args`, `$input`), dynamic variable setters (`Set-Variable`, `function`, `param`, `-OutVariable`), indirect execution (expanded with `[scriptblock]::Create`, `InvokeScript`, and code-level `&` on strings/variables/subexpressions), and unterminated or incomplete scans.

## 0.1.0

- Requires Python 3.11 or newer. The installer rejects older versions.
- Bash backtick checks for shell and monitor calls. Claude reuses its Bash shell, including Git Bash on Windows. Other POSIX shells dispatch to Bash by absolute path. Its startup check reads the user-installed handler or the native plugin's declaration.
- PowerShell checks for backticks in shell calls that contain recognized Git or GitHub CLI text-writing commands.
- Host-specific responses, per-user installation and removal, and a local doctor for registration and synthetic event checks.
- Temporary-home tests, a Windows console runner for code pages 949 and 65001, and an optional test timing multiplier.

See the README for live host measurements, scope and known limitations.
