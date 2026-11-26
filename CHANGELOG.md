# Changelog

## 0.1.0

- Requires Python 3.11 or newer. The installer rejects older versions.
- Bash backtick checks for shell and monitor calls. Claude reuses its Bash shell, including Git Bash on Windows. Other POSIX shells dispatch to Bash by absolute path. Its startup check reads the user-installed handler or the native plugin's declaration.
- PowerShell checks for backticks in shell calls that contain recognized Git or GitHub CLI text-writing commands.
- Host-specific responses, per-user installation and removal, and a local doctor for registration and synthetic event checks.
- Temporary-home tests, a Windows console runner for code pages 949 and 65001, and an optional test timing multiplier.

See the README for live host measurements, scope and known limitations.
