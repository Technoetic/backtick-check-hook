# Security and trust

This package is a text-preservation aid for shell commands. Access controls, command approval, sandboxing and release authorization belong to the host and the operator.

Install from a reviewed source tree using a trusted interpreter. Keep installed scripts, the host configuration and the native plugin root outside repositories that other people can modify. Hook subprocesses receive the event on standard input. The checkers use the Python standard library. Installed Python commands request isolation, UTF-8 mode and suppression of bytecode files. The checkers, adapters and doctor do not persist submitted command text or send it over the network. The host receives a denial reason which may include the command name or a short excerpt and can retain its own transcript.

A Codex trust hash applies to the hook declaration. Review changes to executable files as well. If setup or policy changes, run doctor, confirm the host version and send the harmless probes from the README in the actual session. Treat an unknown version or an unrecorded live probe as an open verification item. Consult the README for parsing limits, error behavior and recovery from a malformed shell hook.

## Report a problem

Use the **Issues** tab of this package's GitHub repository for reports that can be shared publicly. For sensitive reports, use **Security → Report a vulnerability** if the repository offers that option. If it is unavailable, open an issue requesting a private contact channel and withhold the sensitive details.

Give the host version, shell, operating system, and expected and observed results. Use synthetic command text and omit credentials or proprietary content.
