"""Policy, hook protocol, and Bash comparison tests using synthetic input."""
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timing_limits import timing_limit

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS_DIR)
import bash_quote_guard as g  # noqa: E402

SCRIPT = os.path.join(SCRIPTS_DIR, "bash_quote_guard.py")
A = g.RULE_BACKTICK
B = g.RULE_DOLLAR_PAREN

# ---------------------------------------------------------------------------------------------
# 1. 정책
# ---------------------------------------------------------------------------------------------
# 기본 동작에서 막는 것: 실행되는 자리의 백틱
BLOCK = [
    ("double-quoted prose", 'echo "a `date` b"'),
    ("unquoted old-style substitution", "x=`date`"),
    ("unquoted here-document", "cat <<EOF\nuse `ls` here\nEOF"),
    ("here-document with tab stripping", "cat <<-EOF\n\t`ls`\n\tEOF"),
    ("inside ${...} in double quotes", 'echo "${x:-`date`}"'),
    ("inside arithmetic", "echo $(( `echo 1` + 1 ))"),
    ("inside $(...) inside double quotes", 'echo "$(echo `date`)"'),
    ("second of several strings", "echo 'a' \"b `c` d\" 'e'"),
    ("commit message", 'git commit -m "fix `foo` handling"'),
    ("after an escaped backslash", 'echo "a \\\\` b"'),
    ("after a comment line", "echo a # note\nx=`date`"),
    ("escaped space does not start a comment", "echo a\\ #b `date`"),
    ("single quote inside double quotes hides nothing", 'echo "it\'s `date`"'),
    ("after a quoted here-document has ended", "cat <<'EOF'\nliteral\nEOF\necho \"`date`\""),
    ("hash inside a word is not a comment", "echo a#b `date`"),
    ("commit message from an unquoted here-document", 'git commit -m "$(cat <<EOF\nfix `code`\nEOF\n)"'),
    ("here-document closed as EOF) hides nothing after it",
     'git commit -m "$(cat <<\'EOF\'\ntitle\nEOF)" && echo "done `date`"'),
    ("hash inside a regex group is not a comment",
     'while IFS= read -r l; do [[ $l =~ ^[[:space:]]*(#|$) ]] && continue; echo "v `date`"; done < f'),
    ("single quotes do not protect inside arithmetic", "echo $(( '`date`' + 1 ))"),
    ("process id and paren, single quotes inside", 'echo "$$(x \'a `date` b\')"'),
    ("process id and paren, empty double quotes then single quotes", 'echo "$$(x "" \'`date`\')"'),
    # Publishing and formatting examples; the commands here are strings.
    ("python -c with a markdown code span",
     'python -X utf8 -c "print(\'`worker --help` 명령의 도움말\')"'),
    ("grep pattern with optional backticks",
     'grep -n -E "^\\s*-?\\s*`?updated`?|updated:" docs/format.md'),
    ("grep pattern with a code fence", 'grep -n "tests/\\|docs/\\|^```" README.md | tail -22'),
    ("grep bracket expression with one backtick", 'grep -nE "^#|^\\| *[A-Za-z@`]" THIRD_PARTY.md'),
    ("PowerShell escape written inside Bash quotes",
     'powershell -NoProfile -Command "Get-Process | Where-Object { `$_.ProcessName -like \'Demo*\' } | Format-Table"'),
]

# 원문으로는 깨끗하지만 Windows 실행 경로가 역슬래시를 접은 뒤에는 실행되는 명령
BLOCK_ONLY_AFTER_FOLD = [
    ("backtick behind three backslashes", 'echo "a \\\\\\` b"'),
    ("unquoted here-document", "cat <<EOF\n\\\\\\`ls\\\\\\`\nEOF"),
    ("double backslash before a single quote reopens the text", "echo \\\\'a `x` b' 'c'"),
    ("two backslashes end the last body line of an unquoted here-document",
     "cat <<EOF\nrow one \\\\\nEOF\ncat <<'Q'\ntail `echo x`\nQ"),
]

# --strict에서만 막는 것: 글에 섞인 "$("
STRICT_ONLY = [
    ("prose with a substitution", 'echo "now: $(date)"'),
    ("python -c", 'python -c "print(\'$(whoami)\')"'),
    ("substitution then text", 'echo "$(date) start"'),
    ("two substitutions in one string", 'echo "$(date)$(date)"'),
    ("inside ${...} with text around", 'echo "a ${x:-$(date)} b"'),
    ("inside arithmetic with text around", 'echo "a $(( $(date +%s) + 1 ))"'),
    ("unquoted here-document", "cat <<EOF\n$(date)\nEOF"),
    ("commit message", 'git commit -m "docs: explain $(cmd) syntax"'),
    ("inner string mixes text", 'echo "$(echo "inner $(date)")"'),
    ("second assignment", 'x="$(date)" y="pre $(date)"'),
    ("nested shell command line", 'bash -c "echo $(date)"'),
    ("after an escaped backslash", 'echo "a \\\\$(date)"'),
    ("path building", 'python "$(dirname "$0")/x.py"'),
    ("here-string", 'cat <<< "a $(date)"'),
    ("$(( that is really a substitution", 'echo "a $((echo 1); echo 2)"'),
    ("variable next to a substitution", 'echo "$x$(date)"'),
    # 의도한 치환의 예: 기본 동작에서는 통과해야 한다
    ("status line with two command substitutions", 'echo "HEAD=$(git rev-parse --short HEAD) at $(date +%H:%M:%S)"'),
    ("hooks path", 'ls "$(git rev-parse --git-common-dir)/hooks"'),
    ("computed line number", 'sed -n "$(grep -n \'EXAMPLE\' "$F" | head -1 | cut -d: -f1),+5p" "$F"'),
    ("unquoted here-document with a quoted backtick inside a substitution",
     "cat <<EOF\nCode spans: $(grep -c '`' README.md)\nEOF"),
]
STRICT_ONLY_AFTER_FOLD = [("$( behind three backslashes", 'echo "a \\\\\\$(date)"')]

# 두 동작 모두에서 통과해야 하는 것
ALLOW = [
    ("plain", "ls -la"),
    ("single-quoted backticks", "echo 'a `date` b'"),
    ("single-quoted $(", "echo 'now: $(date)'"),
    ("quoted here-document", "cat <<'EOF'\n`ls` $(date)\nEOF"),
    ("double-quoted delimiter", 'cat <<"EOF"\n`ls`\nEOF'),
    ("backslash delimiter", "cat <<\\EOF\n`ls` $(date)\nEOF"),
    ("escaped backticks", 'echo "a \\`date\\` b"'),
    ("escaped $(", 'echo "cost: \\$(5)"'),
    ("read a script file as a single argument",
     'viewer "$(cat "$S/x.js")" > out.txt 2> err.txt; echo "rc=$?"'),
    ("commit message from a quoted here-document",
     'git commit -m "$(cat <<\'EOF\'\nfix `code` and $(x)\n\nCo-Authored-By: Example <test@example.com>\nEOF\n)"'),
    ("assign first", 'x=$(date); echo "a $x"'),
    ("arithmetic", 'echo "$((1+2))" \'`x`\''),
    ("arithmetic in text", 'echo "sum: $((a+b))" \'`x`\''),
    ("whole ${...} with a default command", 'echo "${x:-$(date)}"'),
    ("whole arithmetic with a command", 'echo "$(( $(date +%s) + 1 ))"'),
    ("unquoted substitution", 'echo $(date) "text"'),
    ("comment", "echo a # `not run` $(nor this)"),
    ("ANSI-C string", "echo $'a `b` $(c)'"),
    ("test with a whole-string substitution",
     'if [ "$(git status --porcelain | wc -l)" -gt 0 ]; then echo dirty; fi'),
    ("for loop", 'for f in $(ls); do echo "$f"; done'),
    ("nested whole strings", 'echo "$(echo "$(date)")"'),
    ("PowerShell variables escaped the Bash way",
     'powershell -NoProfile -Command "\\$p = Get-Process; \\$p.Count" # `not run`'),
    ("python from a quoted here-document", "python - <<'PY'\nprint(\"`x`\")\nPY"),
    ("comment after a command", 'grep -c "foo" file # count `foo`'),
    ("case inside a whole-string substitution", 'echo "$(case $x in a) echo 1;; b) echo 2;; esac)" \'`x`\''),
    ("paren in single quotes inside a substitution", 'echo "$(printf \'%s\' \'a)b\')" \'`x`\''),
    ("escaped paren inside a substitution", 'echo "$(echo \\))" \'`x`\''),
    ("comment inside a substitution hides a paren", 'echo "$(echo a # not the end )\n)" \'`x`\''),
    ("arithmetic command", '(( x > 1 )) && echo "$(date)" \'`x`\''),
    ("sed with a backtick in single quotes", "sed -e 's/`/x/g' file"),
    ("awk field in single quotes", "awk '{print $(NF-1)}' file # `x`"),
    ("awk field escaped", 'awk "{print \\$(NF-1)}" file # `x`'),
    ("suffix outside the quotes", 'echo "$(date +%F)"-suffix \'`x`\''),
    ("unquoted here-document without substitutions", "cat <<EOF\nplain $HOME text\nEOF\necho '`x`'"),
    ("substitution holding a quoted here-document", 'echo "$(cat <<\'EOF\'\n`code`\nEOF\n)"'),
    ("printf with whole-string arguments", 'printf \'%s\\n\' "$(date)" "$(whoami)" \'`x`\''),
    ("nested arithmetic parens", 'echo "$(( (1+2) * 3 ))" "$(date)" \'`x`\''),
    ("process substitution", 'diff <(sort a) <(sort b); echo "$(date)" \'`x`\''),
    ("here-string", 'cat <<< "plain text"; echo \'`x`\''),
    ("quote juggling around a single-quoted backtick", "x='a'\"'\"'`mark`'\"'\"'b'"),
    ("line continuation before a comment", "echo a \\\n# `not run`"),
    ("two here-documents, both quoted", ": <<'A' <<'B'\n`x`\nA\n$(y)\nB"),
    ("arithmetic in an unquoted here-document", "cat <<EOF\ntotal $((1+2))\nEOF\necho '`x`'"),
    ("grep pattern moved to single quotes", "grep -n -E '^\\s*-?\\s*`?updated`?|updated:' docs/format.md"),
    ("ANSI-C string with an escaped quote", "echo $'a `x` $(y) \\' `z`'"),
    ("strip backticks from a variable", 'v="${v//\'`\'/}"; c="${c#\'`\'}"; echo "$v$c"'),
    ("backtick escaped with one backslash next to a variable", 'git commit -m "fix \\`foo\\` for $USER"'),
    ("case arm with single-quoted text inside a whole-string substitution",
     'out="$(if case $u in a) true;; *) false;; esac; then echo \'yes `x`\'; fi)"; echo "$out"'),
]


class PolicyTests(unittest.TestCase):
    def test_blocks_backticks_by_default(self):
        for name, command in BLOCK:
            with self.subTest(name=name):
                found = g.find_violations(command)
                self.assertTrue(found, "not blocked: %r" % command)
                self.assertEqual({v.rule for v in found}, {A})
                self.assertEqual(found[0].variant, g.AS_WRITTEN)
                self.assertTrue(g.find_violations(command, strict=True))

    def test_blocks_what_only_runs_after_the_launcher_folds_backslashes(self):
        for name, command in BLOCK_ONLY_AFTER_FOLD:
            with self.subTest(name=name):
                self.assertEqual(g.scan(command)[0], [], "the text as written should look clean: %r" % command)
                found = g.find_violations(command)
                self.assertTrue(found, "not blocked: %r" % command)
                self.assertEqual(found[0].variant, g.FOLDED)
                self.assertEqual({v.rule for v in found}, {A})
                self.assertIn("Windows launcher", g.format_message(found))

    def test_dollar_paren_in_text_is_blocked_only_in_strict_mode(self):
        for name, command in STRICT_ONLY:
            with self.subTest(name=name):
                self.assertEqual(g.find_violations(command), [], "blocked by default: %r" % command)
                found = g.find_violations(command, strict=True)
                self.assertTrue(found, "not blocked in strict mode: %r" % command)
                self.assertEqual({v.rule for v in found}, {B})
                self.assertEqual(found[0].variant, g.AS_WRITTEN)
        for name, command in STRICT_ONLY_AFTER_FOLD:
            with self.subTest(name=name):
                self.assertEqual(g.find_violations(command), [])
                found = g.find_violations(command, strict=True)
                self.assertEqual((found[0].rule, found[0].variant), (B, g.FOLDED))

    def test_allows(self):
        for name, command in ALLOW:
            with self.subTest(name=name):
                self.assertEqual(g.find_violations(command), [], "blocked: %r" % command)
                self.assertEqual(g.find_violations(command, strict=True), [], "blocked in strict mode: %r" % command)

    def test_commands_without_a_backtick_are_not_even_read(self):
        saved = g.scan
        g.scan = lambda *a, **k: (_ for _ in ()).throw(AssertionError("scan must not run"))
        try:
            self.assertEqual(g.find_violations('echo "now: $(date)" \'quote'), [])
        finally:
            g.scan = saved

    def test_position_and_excerpt(self):
        found = g.find_violations("echo one\necho two\necho \"x `date`\"")
        self.assertEqual((found[0].line, found[0].col), (3, 9))
        self.assertIn("`date`", found[0].near)
        self.assertEqual(found[0].where, "double-quoted text")

    def test_message_names_the_fix_in_two_languages(self):
        text = g.format_message(g.find_violations('echo "a `date` b"'))
        self.assertIn("[backtick-check-hook]", text)
        self.assertIn("BLOCKED", text)
        self.assertIn("file-writing tool", text)
        self.assertIn("PowerShell", text)
        self.assertIn("실행 전에 막았습니다", text)
        self.assertNotIn("Windows launcher", text)
        self.assertNotIn("strict mode", text)
        self.assertIn("strict mode", g.format_message(g.find_violations('echo "a $(date)"', strict=True)))

    def test_many_violations_are_summarised(self):
        text = g.format_message(g.find_violations("echo " + " ".join('"`a%d`"' % i for i in range(9))))
        self.assertIn("and 5 more", text)

    def test_too_deep_nesting_is_let_through(self):
        command = 'echo ' + '"$(echo ' * 400 + 'x `date`' + ')"' * 400
        self.assertEqual(g.find_violations(command), [])

    def test_long_command_does_not_fail(self):
        command = "printf '%s\\n' " + " ".join("'item `%d`'" % i for i in range(20000)) + ' "$(date)"'
        self.assertEqual(g.find_violations(command), [])
        self.assertTrue(g.find_violations(command + ' "`date`"'))

    def test_giving_up_keeps_what_was_already_found(self):
        """깊이 제한에 걸려 읽기를 그만둬도 그 앞에서 찾은 백틱은 버리지 않는다."""
        command = 'echo "a `date` b"\n: ' + "${u:-" * 400 + "x" + "}" * 400
        found = g.find_violations(command)
        self.assertEqual([(v.rule, v.line) for v in found], [(A, 1)])

    def test_nested_non_arithmetic_double_parens_stay_fast(self):
        """ "$(( " 가 산술이 아닐 때 다시 읽는 일이 겹칠 때마다 두 배가 되지 않는다(40겹이 1초 안)."""
        command = ": " + "$(( " * 40 + "x" + " ) )" * 40 + ' "`date`"'
        started = time.perf_counter()
        found = g.find_violations(command)
        self.assertLess(time.perf_counter() - started, timing_limit(1.0))
        self.assertEqual([v.rule for v in found], [A])

    def test_running_out_of_time_does_not_raise(self):
        saved = g.TIME_BUDGET
        g.TIME_BUDGET = -1.0       # 시작하자마자 시간이 다 된 것으로 친다
        try:
            self.assertEqual(g.find_violations('echo "$(echo "$(echo "`date`")")"'), [])
        finally:
            g.TIME_BUDGET = saved
        self.assertTrue(g.find_violations('echo "$(echo "$(echo "`date`")")"'))

    def test_unpaired_backtick_is_reported_once(self):
        text = "x -Command \"Where-Object { `$_.Name -like 'a*' }\"; echo \"plain\"; echo 'sq `y` end'"
        found = g.find_violations(text)
        self.assertEqual([(v.col, v.where) for v in found][:1], [(28, "double-quoted text")])
        self.assertNotIn(75, [v.col for v in found])

    @unittest.skipUnless(g.STRIP_CR, "only Git Bash on Windows drops carriage returns")
    def test_carriage_returns_are_dropped_the_way_git_bash_drops_them(self):
        crlf = "x <<'EOF' > /dev/null\r\nbody\r\nEOF\r\necho \"a `date` b\"\r\n"
        self.assertEqual([v.rule for v in g.find_violations(crlf)], [A])
        self.assertEqual(g.find_violations("cat <<'EOF'\r\n`x`\r\nEOF\r\n"), [])

    def test_fold_note_says_the_typed_text_is_clean(self):
        text = g.format_message(g.find_violations('echo "a \\\\\\` b"'))
        self.assertIn("the text as you typed it is clean", text)
        self.assertIn("short", text)
        self.assertIn("exactly ONE backslash", text)

    def test_cases_blocked_out_of_caution(self):
        """판정이 실행 환경에 달린 자리는 막는다: 연관 배열인지 알 수 없는 첨자, 본문 없이 닫힌 히어독."""
        self.assertTrue(g.find_violations('declare -A m; m[k]=v; echo "${m[\'`k`\']}"'))
        self.assertTrue(g.find_violations('echo "$(x <<\'E\') tail\n`y`\nE\n"'))


# ---------------------------------------------------------------------------------------------
# 역슬래시 접힘
# ---------------------------------------------------------------------------------------------
# (Typed text, text received by the Windows Bash launcher).
MEASURED_FOLD = [
    ("1:\\x", "1:\\x"),
    ("2:\\\\x", "2:\\x"),
    ("3:\\\\\\x", "3:\\\\x"),
    ("4:\\\\\\\\x", "4:\\\\x"),
    ("5:\\\\\\\\\\x", "5:\\\\\\x"),
    ('q1:\\"', 'q1:\\"'),
    ('q2:\\\\"', 'q2:\\\\"'),
    ('q3:\\\\\\"', 'q3:\\\\\\"'),
    ("b2:\\\\`", "b2:\\`"),
    ("d2:\\\\$(", "d2:\\$("),
    ("s2:\\\\'", "s2:\\'"),
    ("A\\\\+B", "A\\+B"),
    ("n2:\\\\\nend", "n2:\\\nend"),
]
# 같은 날 검토 에이전트가 Bash 도구로 71줄을 더 재서 확인한 값(모형과 어긋난 줄 0)
MEASURED_FOLD += [
    ("6:" + "\\" * 6 + "x", "6:" + "\\" * 3 + "x"),
    ("7:" + "\\" * 7 + "x", "7:" + "\\" * 4 + "x"),
    ("b3:" + "\\" * 3 + "`", "b3:" + "\\" * 2 + "`"),
    ("b6:" + "\\" * 6 + "`", "b6:" + "\\" * 3 + "`"),
    ("b7:" + "\\" * 7 + "`", "b7:" + "\\" * 4 + "`"),
    ("q4:" + "\\" * 4 + '"', "q4:" + "\\" * 4 + '"'),
    ("q5:" + "\\" * 5 + '"', "q5:" + "\\" * 5 + '"'),
    ("sq:" + "\\" * 2 + "'\"", "sq:" + "\\" + "'\""),
    ("sp:" + "\\" * 4 + " z", "sp:" + "\\" * 2 + " z"),
]
# 명령의 맨 끝에 놓인 역슬래시 줄도 접힌다(Bash 도구 실측: 3개 -> 2개, 5개 -> 3개).
# 파이썬에서 bash.exe를 바로 띄우면 맨 끝만은 접히지 않으므로 이 둘은 실행 경로 시험에 넣지 않는다.
MEASURED_FOLD_AT_END = [("x" + "\\" * 3, "x" + "\\" * 2), ("x" + "\\" * 5, "x" + "\\" * 3)]


class FoldTests(unittest.TestCase):
    def test_model_matches_the_measured_table(self):
        for typed, received in MEASURED_FOLD + MEASURED_FOLD_AT_END:
            with self.subTest(typed=typed):
                self.assertEqual(g.fold_backslashes(typed), received)

    def test_text_without_double_backslashes_is_unchanged(self):
        for text in ["", "plain", 'a \\` b \\$( c \\" d', "C:\\data\\x"]:
            self.assertEqual(g.fold_backslashes(text), text)


# ---------------------------------------------------------------------------------------------
# 2. 훅 규약
# ---------------------------------------------------------------------------------------------
def _run_hook(payload, *args):
    data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    p = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", SCRIPT, *args], input=data,
                       capture_output=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def _bash_payload(command):
    return {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": command, "description": "d"}}


class HookProtocolTests(unittest.TestCase):
    def test_clean_command_exits_zero_silently(self):
        self.assertEqual(_run_hook(_bash_payload("ls -la")), (0, b"", b""))
        self.assertEqual(_run_hook(_bash_payload("echo 'a `date` b'")), (0, b"", b""))

    def test_violation_exits_two_with_reason_on_stderr(self):
        rc, out, err = _run_hook(_bash_payload('echo "한글 `date` 글"'))
        self.assertEqual(rc, 2)
        self.assertEqual(out, b"")
        text = err.decode("utf-8")
        self.assertIn("[backtick-check-hook]", text)
        self.assertIn("BLOCKED", text)
        self.assertIn("한글 `date` 글", text)
        self.assertIn("실행 전에 막았습니다", text)

    def test_block_code_can_be_changed(self):
        self.assertEqual(_run_hook(_bash_payload('echo "`date`"'), "--block-code=42")[0], 42)
        self.assertEqual(_run_hook(_bash_payload("ls"), "--block-code=42")[0], 0)
        self.assertEqual(_run_hook(_bash_payload('echo "`date`"'), "--block-code=zero")[0], 2)
        self.assertEqual(_run_hook(_bash_payload('echo "`date`"'), "--block-code=0")[0], 2)

    def test_strict_flag_adds_the_dollar_paren_rule(self):
        self.assertEqual(_run_hook(_bash_payload('echo "now: $(date)"'))[0], 0)
        rc, _out, err = _run_hook(_bash_payload('echo "now: $(date)"'), "--strict")
        self.assertEqual(rc, 2)
        self.assertIn("strict mode", err.decode("utf-8"))

    def test_monitor_commands_are_checked_too(self):
        monitor = {"tool_name": "Monitor", "tool_input": {"command": 'tail -f x | grep "a `date` b"',
                                                          "description": "d", "timeout_ms": 1000}}
        rc, _out, err = _run_hook(monitor)
        self.assertEqual(rc, 2)
        self.assertTrue(err.startswith(b"[bash-quote-guard] BLOCKED"))
        monitor["tool_input"]["command"] = "tail -f x | grep 'a `date` b'"
        self.assertEqual(_run_hook(monitor)[0], 0)
        socket = {"tool_name": "Monitor", "tool_input": {"ws": {"url": "wss://x"}, "description": "`d`"}}
        self.assertEqual(_run_hook(socket)[0], 0)

    def test_other_tools_are_ignored(self):
        rc, _out, err = _run_hook({"tool_name": "Write", "tool_input": {"command": 'echo "`date`"',
                                                                         "content": "`x`"}})
        self.assertEqual((rc, err), (0, b""))

    def test_broken_input_never_blocks(self):
        for payload in [b"", b"not json `x`", b"[1, 2]", b'{"tool_name": "Bash"}',
                        b'{"tool_name": "Bash", "tool_input": {"command": 5}}',
                        b'{"tool_name": "Bash", "tool_input": "`x`"}', b"\xff\xfe\x00`"]:
            with self.subTest(payload=payload):
                rc, _out, err = _run_hook(payload)
                self.assertEqual((rc, err), (0, b""))

    def test_a_block_always_comes_with_a_reason(self):
        """쓸 수 없는 글자(짝 없는 대리 문자)가 발췌에 들어가도 이유 없이 막지 않는다."""
        payload = ('{"tool_name":"Bash","tool_input":{"command":"echo \\"a \\' + 'ud800 `date` b\\""}}').encode("ascii")
        rc, _out, err = _run_hook(payload)
        self.assertEqual(rc, 2)
        self.assertTrue(err.startswith(b"[bash-quote-guard] BLOCKED"))

    def test_byte_order_mark_is_accepted(self):
        payload = b"\xef\xbb\xbf" + json.dumps(_bash_payload("x=`date`")).encode()
        self.assertEqual(_run_hook(payload)[0], 2)

    def test_raw_mode_reads_the_command_itself(self):
        self.assertEqual(_run_hook('echo "a `date` b"'.encode(), "--raw")[0], 2)
        self.assertEqual(_run_hook("echo 'a `date` b'".encode(), "--raw")[0], 0)

    def test_internal_failure_lets_the_command_through(self):
        saved_scan, saved_stdin = g.scan, sys.stdin
        g.scan = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))

        class _In:
            buffer = io.BytesIO(json.dumps(_bash_payload('echo "`date`"')).encode())

        try:
            sys.stdin = _In()
            self.assertEqual(g.main([]), 0)
        finally:
            sys.stdin = saved_stdin
            g.scan = saved_scan


# ---------------------------------------------------------------------------------------------
# 3. 실제 Bash 대조
# ---------------------------------------------------------------------------------------------
def _find_bash():
    cands = [os.environ.get("BASH_QUOTE_GUARD_BASH"), shutil.which("bash")]
    git = shutil.which("git")
    if git:
        up1 = os.path.dirname(os.path.dirname(os.path.abspath(git)))
        up2 = os.path.dirname(up1)
        for root in (up1, up2):
            cands += [os.path.join(root, "bin", "bash.exe"), os.path.join(root, "usr", "bin", "bash.exe")]
    cands += [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe",
              "/bin/bash", "/usr/bin/bash"]
    sysroot = os.path.abspath(os.environ.get("SystemRoot") or r"C:\Windows").lower()
    for c in cands:
        if not c or not os.path.isfile(c):
            continue
        low = os.path.abspath(c).lower()
        if os.name == "nt" and (low.startswith(sysroot) or "windowsapps" in low):
            continue   # WSL을 띄우는 실행 파일이지 Bash 자체가 아니다
        try:
            p = subprocess.run([c, "--version"], capture_output=True, timeout=30)
        except Exception:
            continue
        if p.returncode == 0 and b"GNU bash" in p.stdout:
            return c
    return None


BASH = _find_bash()
BASH_VERSION = ()
if BASH:
    version = subprocess.check_output([BASH, "--version"], timeout=10)
    match = re.search(rb"\b(\d+)\.(\d+)\.", version)
    if match:
        BASH_VERSION = tuple(int(n) for n in match.groups())

# 사례마다 하위 셸에서 PATH를 비우고 읽어 들인다. mark는 명령 치환 안에서 불렸을 때만 RAN을 찍는다.
DRIVER = """mark() { if [ "$BASH_SUBSHELL" -ge 2 ]; then printf RAN >&2; fi; }
x() { :; }
w=abc
dir=$1
for f in "$dir"/c*.sh; do
  ( PATH=/nonexistent; . "$f" ) > /dev/null 2> "$f.err" < /dev/null
done
: > "$dir/finished.flag"
exit 0
"""


def run_in_bash(cases):
    """사례 글 목록을 진짜 Bash로 실행해 [(RAN이 찍혔는가, 그 밖의 표준 오류)]를 돌려준다."""
    with tempfile.TemporaryDirectory(prefix="bqg-") as tmp:
        driver = os.path.join(tmp, "driver.sh")
        with open(driver, "w", encoding="utf-8", newline="\n") as f:
            f.write(DRIVER)
        cdir = os.path.join(tmp, "cases")
        os.mkdir(cdir)
        for i, text in enumerate(cases):
            with open(os.path.join(cdir, "c%05d.sh" % i), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        driver_env = dict(os.environ)
        driver_env.pop("BASH_ENV", None)
        driver_env.pop("ENV", None)
        p = subprocess.run([BASH, "--noprofile", "--norc", driver.replace("\\", "/"), cdir.replace("\\", "/")],
                           capture_output=True, timeout=1800, cwd=tmp, env=driver_env)
        if p.returncode != 0 or not os.path.isfile(os.path.join(cdir, "finished.flag")):
            raise RuntimeError("driver failed: rc=%s %r" % (p.returncode, p.stderr[-400:]))
        out = []
        for i in range(len(cases)):
            with open(os.path.join(cdir, "c%05d.sh.err" % i), "rb") as f:
                err = f.read().decode("utf-8", "replace")
            out.append(("RAN" in err, err.replace("RAN", "").strip()))
        return out


def lexer_sees_a_substitution(text):
    return bool(g.read_both_ways(g.as_bash_reads(text))[1])


def lexer_sees_mark_run(text):
    """검사기가 '실행된다'고 본 치환 가운데 `mark`나 $(mark)가 있는가(무작위 대조용)."""
    text = g.as_bash_reads(text)
    return any(text.startswith("`mark`", i) or text.startswith("$(mark)", i)
               for _kind, i in g.read_both_ways(text)[1])


# (이름, 글, 명령 치환이 실제로 도는가). 모두 한 줄씩 그대로 실행되는 글이다.
CURATED = [
    ("double quotes", 'echo "a `mark` b"', True),
    ("unquoted backticks", "echo `mark`", True),
    ("unquoted $(", "echo $(mark)", True),
    ("whole-string $(", 'echo "$(mark)"', True),
    ("$( in text", 'echo "a $(mark)"', True),
    ("unquoted here-document, backtick", ": <<E\n`mark`\nE", True),
    ("unquoted here-document, $(", ": <<E\n$(mark)\nE", True),
    ("tab-stripped here-document", ": <<-E\n\t$(mark)\n\tE", True),
    ("${...} default in double quotes", 'echo "${u:-`mark`}"', True),
    ("${...} default with $(", 'echo "${u:-$(mark)}"', True),
    ("single quotes inside a double-quoted ${...} are plain text", 'echo "${u:-\'`mark`\'}"', True),
    ("arithmetic with backticks", "echo $(( `mark` + 1 ))", True),
    ("arithmetic with $( in double quotes", 'echo "$(( $(mark) + 1 ))"', True),
    ("escaped space, then a hash inside the word", "echo a\\ #b `mark`", True),
    ("escaped backslash, then a live backtick", 'echo "a \\\\`mark`"', True),
    ("two escaped backslashes, then a live backtick", 'echo "\\\\\\\\`mark`"', True),
    ("between single-quoted strings", "echo 'a'`mark`'b'", True),
    ("hash glued to a quoted string", 'echo "x"#`mark`', True),
    ("hash inside a word", "echo a#b `mark`", True),
    ("comment ends at the newline", "echo a;#c\necho `mark`", True),
    ("comment inside $( hides the paren", "y=$(echo 1 # c)\n`mark`\n)", True),
    ("case inside $(", "echo $(case a in a) mark;; esac)", True),
    ("paren in quotes inside $(", 'echo "$(echo \')\' `mark`)"', True),
    ("after an ANSI-C string", "echo $'a'`mark`", True),
    ("after an arithmetic command", "((1)); echo `mark`", True),
    ("after arithmetic expansion", "echo $((1)) `mark`", True),
    ("third string", 'echo "a" \'b\' "c `mark`"', True),
    ("escaped backslash in an unquoted here-document", ": <<E\n\\\\`mark`\nE", True),
    ("quoted hash, then a backtick", 'echo "#" `mark`', True),
    ("dollar-hash, then a backtick", "echo $#`mark`", True),
    ("length expansion, then a backtick", "echo ${#u}`mark`", True),
    ("same line as the here-document operator", ": <<E; echo `mark`\nbody\nE", True),
    ("first of two here-documents is unquoted", ": <<A <<'B'\n`mark`\nA\n`mark`\nB", True),
    ("second of two here-documents is unquoted", ": <<'A' <<B\nA\n$(mark)\nB", True),
    ("$(( that is really a substitution", "echo $((mark); x)", True),
    ("(( that is really two subshells", "((x); `mark`)", True),
    ("subshell", "( echo `mark` )", True),
    ("group", "{ echo `mark`; }", True),
    ("after a here-string", ": <<< 'a' `mark`", True),
    ("dollar-quote string", 'echo $"a `mark`"', True),
    ("nested double quotes inside ${...}", 'echo "${u:-"a `mark`"}"', True),
    ("backtick in a quoted string after a backslash-newline", 'echo "a\\\n`mark`"', True),
    ("grep-style pattern in double quotes", ': "^#|^[A-Za-z@`mark`]"', True),
    ("PowerShell-style escape in double quotes", ': "{ `mark`$_.Name }"', True),
    ("process id and paren: single quotes inside hide nothing", 'echo "$$(x \'a `mark` b\')"', True),
    ("process id and paren: empty double quotes, then single quotes", 'echo "$$(x "" \'`mark`\')"', True),
    ("process id and paren: backtick in nested double quotes", 'echo "$$(x "`mark`")"', True),
    ("three dollars: process id, then a real substitution", 'echo "$$$(mark)"', True),
    ("process id and paren around a real substitution", 'echo "$$(a $(mark) b)"', True),
    ("question mark parameter and paren", 'echo "$?(x \'a `mark` b\')"', True),
    ("process id followed by a paren is not a substitution", 'echo "$$(mark)"', False),
    ("four dollars followed by a paren", 'echo "$$$$(mark)"', False),
    ("positional parameter followed by a paren", 'echo "$1(mark)"', False),
    ("process id followed by a paren in an unquoted here-document", ": <<E\n$$(mark)\nE", False),
    ("single quotes", "echo 'a `mark` b'", False),
    ("single-quoted $(", "echo 'a $(mark) b'", False),
    ("escaped backticks", 'echo "a \\`mark\\` b"', False),
    ("escaped $(", 'echo "a \\$(mark) b"', False),
    ("comment", "echo a # `mark` $(mark)", False),
    ("quoted here-document", ": <<'E'\n`mark` $(mark)\nE", False),
    ("double-quoted delimiter", ': <<"E"\n`mark`\nE', False),
    ("backslash delimiter", ": <<\\E\n$(mark)\nE", False),
    ("ANSI-C string", "echo $'a `mark` $(mark) \\' `mark`'", False),
    ("three backslashes: escaped backslash, escaped backtick", 'echo "a \\\\\\`mark\\\\\\` b"', False),
    ("escaped in an unquoted here-document", ": <<E\n\\`mark\\` \\$(mark)\nE", False),
    ("line continuation, then a comment", "echo a \\\n# `mark`", False),
    ("arithmetic only", 'echo "$((1+2))"', False),
    ("escaped backticks outside quotes", "echo \\`mark\\`", False),
    ("quote juggling", "v='a'\"'\"'`mark`'\"'\"'b'", False),
    ("single quotes after a string that holds quotes", 'echo "a \'b\' c" \'`mark`\'', False),
    ("single quotes inside an unquoted ${...}", "echo ${u:-'`mark`'}", False),
    ("comment after a quoted string", 'echo "a" # "`mark`"', False),
    ("comment after the here-document operator", ": <<E # `mark`\nx\nE", False),
    ("quoted here-document with a command on its line", ": <<'E'; echo ok\n`mark`\nE", False),
    ("both here-documents quoted", ": <<'A' <<'B'\n`mark`\nA\n$(mark)\nB", False),
    ("comment after a semicolon", "echo a;# `mark`", False),
    ("comment at the start", "# `mark`\necho a", False),
    ("comment after a subshell opens", "( # `mark`\necho a )", False),
]


# Parser regression corpus with declared Bash execution expectations.
# 줄 "=== 이름 | 종류" 다음부터 다음 "===" 앞까지가 글이다. <CR>은 CR 문자, <TAB>은 탭이다.
# 종류: ran(실제로 돈다, Bash가 군말 없음) · dead(돌지 않는다) · ran-noisy(돈다, Bash가 경고나 오류도 낸다)
#       dead-noisy(돌지 않고 막지도 않는다, Bash가 경고를 낸다) · caution(돌지 않지만 검사기가 일부러 막는다)
REVIEW_CASES_TEXT = r'''
=== here-document closed as "EOF)" inside a commit substitution | ran-noisy
x commit -m "$(x <<'EOF'
subject
EOF)" && echo "done `mark`"
=== here-document closed as "EOF)" then a later line | ran-noisy
msg=$(x <<'EOF'
plain text
EOF)
echo "live `mark`"
=== here-document closed as "EOF )" | ran-noisy
msg=$(x <<'EOF'
plain
EOF )
echo "live `mark`"
=== body line that starts with the delimiter and holds a paren | ran-noisy
v=$(x <<'PY'
PY ok )
echo "a `mark` b"
=== the same in process substitution | ran-noisy
x < <(x <<'E'
body
E)
echo "a `mark` b"
=== plain subshell does not end the body at "E)" | dead
(x <<'E'
body
E)
echo "a `mark` b"
E
)
=== unquoted here-document closed as "EOF)" then single-quoted text | dead-noisy
msg=$(x <<EOF
plain $HOME text
EOF)
printf '%s\n' "$msg" 'done `mark`'
=== regex group holding a hash, one line | ran
while IFS= read -r l; do [[ $l =~ ^[[:space:]]*(#|$) ]] && continue; echo "v `mark`"; done <<< 'k'
=== regex with an optional comment group | ran
while IFS= read -r l; do [[ $l =~ ^[[:space:]]*(#.*)?$ ]] && continue; echo "use `mark`"; done <<< 'k'
=== regex loop captured in double quotes, then a commit message | ran
out="$(while IFS= read -r line; do
  [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
  printf '%s\n' "$line"
done <<< 'k')"
x commit -m "fix #12: handle `mark` properly"
=== regex group with a blank before the hash | ran
[[ 'a #' =~ (a #) ]] && echo "x `mark`"
=== extended glob in a condition | ran
[[ abc == @(#|abc) ]] && echo "x `mark` y"
=== hash after process substitution | ran
: <(x)#c `mark`
=== hash after an array assignment | ran
a=(1 2)#c `mark`
=== comment inside an array assignment | dead
a=(1 2 # `mark`
3)
=== carriage returns around a quoted here-document | ran
x <<'EOF' > /dev/null<CR>
body<CR>
EOF<CR>
echo "a `mark` b"<CR>
=== carriage return inside single quotes | dead
echo 'a<CR>`mark`'
=== backslash, carriage return, newline is a line continuation | ran
echo a\<CR>
#b `mark`<CR>
=== single quotes in arithmetic expansion | ran-noisy
echo $(( '`mark`' + 1 ))
=== single quotes in an arithmetic command | ran-noisy
(( '`mark`' + 1 ))
=== ANSI-C string in arithmetic | ran-noisy
echo $(( $'`mark`' + 1 ))
=== single quotes in old-style arithmetic | ran-noisy
echo $[ '`mark`' + 1 ]
=== single quotes in a substring offset | ran-noisy
u=abc; : ${u:'`mark`'}
=== single quotes in an indexed subscript | ran-noisy
: ${u['`mark`']}
=== single quotes in an assignment subscript | ran-noisy
a['`mark`']=1
=== single quotes in a for-loop header | ran-noisy
for (( i='`mark`'0; i<1; i++ )); do :; done
=== shift inside old-style arithmetic is not a here-document | dead
echo $[1<<2]
echo 'after `mark`'
=== shift inside an assignment subscript is not a here-document | dead
arr[1<<2]=5
echo 'after `mark`'
=== a glob bracket is not a subscript | dead
echo x[ab] 'q `mark`'
=== case word holding a semicolon | ran
echo "$(case "a;b" in *) echo "it's `mark` time";; esac)"
=== case after if | ran
echo "$(if case a in *) true;; esac; then echo "it's `mark` time"; fi)"
=== case after while | ran
echo "$(while case a in *) false;; esac; do :; done; echo "it's `mark` time")"
=== case with a line continuation | ran
echo "$(case \
a in *) echo "it's `mark` time";; esac)"
=== esac used as an argument | ran
echo "$(case b in a) echo esac;; *) echo "it's `mark` time";; esac)"
=== the words case a in after a substitution | ran
echo "$(echo $(x) case a in ) it's `mark` isn't"
=== the words case a in inside a for list | ran
echo "$(for w in case a in; do :; done) it's `mark` isn't"
=== the words case b in on a continuation line | ran
echo "$(echo a \
case b in ) it's `mark` isn't"
=== case arm with single-quoted text after if | dead
out="$(if case $u in a) true;; *) false;; esac; then echo 'yes `mark`'; fi)"; echo "$out"
=== case word with a semicolon, single-quoted arm | dead
r="$(case "$a;$b" in x\;y) echo 'm `mark`';; *) echo n;; esac)"; echo "$r"
=== case word that is a substitution, single-quoted arm | dead
kind="$(case "$(x -d';' -f1 <<< "$line")" in a) echo 'A `mark`';; *) echo other;; esac)"; echo "$kind"
=== case inside a function body | dead
y="$(f() { case a in a) echo 'q `mark`';; esac; }; f)"
=== backslash before the delimiter line joins it to the body | ran-noisy
x <<E
text \
E
echo 'a `mark` b'
E
=== the same with a quoted here-document after it | ran-noisy
x <<EOF
row one \
EOF
x <<'Q'
tail `mark`
Q
=== tab-stripped delimiter after a continuation does not end the body | ran-noisy
x <<-E
<TAB>abc \
<TAB>E
<TAB>'`mark`'
=== delimiter on the next line after a continuation | ran
x << \
E
a `mark` b
E
=== ANSI-C delimiter | ran
x <<$'E'
body
E
echo "a `mark` b"
=== here-document operator before a multi-line substitution | ran
x <<'E' "$(x
echo "q `mark` r")"
body
E
=== substitution closed before its here-document body, code on the same line | ran-noisy
v=$(x <<'E') "`mark`"
E
=== substitution closed before its here-document body, quoted body follows | caution
echo "$(x <<'E') tail
`mark`
E
"
=== single quote pairs inside a double-quoted default: brace and quote | ran
echo "${x:-'}"'}" `mark`
=== single quote pairs inside a double-quoted default: quote, then text | ran
echo "${x:-'"'}" a } "it's `mark` time"
=== single quotes inside a double-quoted default hold a brace | dead
echo "${u:-'}'}" '`mark`'
=== pattern removal with a single-quoted backtick | dead
v='a`b'; echo "${v//'`'/}"
=== pattern holding a code span | dead
v=abc; echo "${v//'`mark`'/}"
=== prefix and suffix removal | dead
c='`cell`'; c="${c#'`'}"; c="${c%'`'}"; echo "$c"
=== replacement text in single quotes | dead
v=axc; echo "${v//x/'`mark`'}"
=== double quote inside a single-quoted pattern | dead
s='say "hi"'; echo "${s//'"'/}" 'and `mark`'
=== ANSI-C string as a pattern | dead
v=abc; echo "${v//$'`mark`'/}"
=== pattern applied to an array | dead
cells=('`a`' '`b`'); printf '%s\n' "${cells[@]//'`'/}"
=== code fence in a suffix pattern | dead
l='```bash'; [[ "${l%%'```'*}" != "$l" ]] && echo fence
=== pattern expansion inside a nested substitution | dead
v='a`b'; x "$(x "${v//'`'/}")"
=== single replacement with an escaped quote | dead
v='a`b'; echo "${v/'`'/\'}"
=== unquoted default keeps its single quotes | dead
echo ${u:-'`mark`'}
=== associative subscript (the guard cannot know the array kind) | caution
declare -A m; m[k]=v; echo "${m['`k`']}"
=== unquoted here-document: quoted backtick inside a substitution | dead
x <<EOF
Code spans: $(x -c '`' README.md)
Fences: $(x -c '^```' README.md)
EOF
=== unquoted here-document: sed script inside a substitution | dead
x <<EOF
Files: $(x 's/`mark`//g')
Home: $HOME
EOF
=== unquoted here-document: pattern expansions | dead
v='a`b'
x <<EOF
Clean: $(x "${v//\`/}") and $(x ${v//'`'/})
EOF
=== unquoted here-document: live backtick inside a substitution's double quotes | ran
x <<EOF
$(x "a `mark` b")
EOF
=== function substitution with single-quoted text | dead
echo "${ x 'a `mark` b'; }"
=== function substitution with double-quoted text | ran
echo "${ x "a `mark` b"; }"
=== function substitution: apostrophe in a comment | ran
v=${ x # don't
echo "a `mark` b"; }
=== function substitution holding an unquoted here-document | ran
v=${ x <<E
'`mark`'
E
}
=== nested non-arithmetic double parens | ran
: $(( $(( $(( x ) ) ) ) ) ) "`mark`"
=== escaped double quote inside a string, then a backtick | ran
echo "say \"it's `mark`\" now"
=== escaped double quote, then single-quoted text | dead
echo "a \" b" 'c `mark` d'
=== single-quoted Windows path ending in a backslash | ran
echo 'C:\dir\' "a `mark` b"
=== backslash before a closing single quote, more single quotes | dead
echo 'a\' 'b' 'c `mark` d'
=== blank between the operator and an unquoted delimiter | ran
: << E
it's `mark` here
E
=== blank between the operator and a quoted delimiter | dead
: << 'E'
a `mark` b
E
=== string ending in a dollar sign, then single quotes | dead
echo "foo$" 'a `mark` b'
=== string ending in a dollar sign, a quote character, then a string | ran
echo "foo$" '"' "it's `mark`"
=== tab-stripped quoted here-document, then a live line | ran
: <<-'E'
<TAB>body
<TAB>E
echo "a `mark` b"
=== tab-stripped unquoted here-document, then single quotes | dead
: <<-E
<TAB>body
<TAB>E
echo 'a `mark` b'
=== dollar-apostrophe inside double quotes is not a string start | ran
echo "end$'s `mark` here"
=== the word case in argument position, single quotes after | dead
echo "$(echo case x in y)" 'a `mark` b'
=== the word case in argument position, a string after | ran
echo "$(echo case x in y)" "it's `mark`"
=== case arm holding a double quote in single quotes | dead
echo "$(case x in a) echo 'it"s';; esac)" '`mark`'
=== substitution closed on the operator line, unquoted body follows | ran-noisy
x=$(: <<E)
echo 'a `mark` b'
E
=== substitution closed on the operator line, quoted body follows | caution
x=$(: <<'E')
echo "a `mark` b"
E
=== unquoted body: inner quoted delimiter followed by a continuation | ran
: <<E
$(: <<'Q'
abc
Q\

`mark`
)
E
=== unquoted body: a continuation glues text to the inner delimiter | ran
: <<E
$(: <<'Q'
abc\
Q
it's
Q
echo `mark` # '
)
E
=== unquoted body: a continuation extends a comment | ran
: <<E
$(: # c\
'
echo `mark` # '
)
E
=== continuation after the delimiter inside a substitution | ran-noisy
x=$(: <<E
abc
E\
) ; : '$(' `mark` ')'
'''


def _review_cases():
    out = []
    name = kind = None
    lines = []
    for line in REVIEW_CASES_TEXT.strip("\n").split("\n") + ["=== end | end"]:
        if line.startswith("=== "):
            if name is not None:
                out.append((name, "\n".join(lines).replace("<CR>", "\r").replace("<TAB>", "\t"), kind))
            name, kind = [part.strip() for part in line[4:].rsplit("|", 1)]
            lines = []
        else:
            lines.append(line)
    return out


REVIEW_CASES = _review_cases()


@unittest.skipUnless(BASH, "no usable bash (Git Bash) on this machine")
class RealBashTests(unittest.TestCase):
    @unittest.skipUnless(BASH_VERSION >= (5, 3), "review fixtures use Bash 5.3 syntax")
    def test_review_cases_agree_with_bash(self):
        self.assertGreaterEqual(len(REVIEW_CASES), 70)
        results = run_in_bash([text for _name, text, _kind in REVIEW_CASES])
        for (name, text, kind), (ran, other) in zip(REVIEW_CASES, results):
            with self.subTest(name=name):
                self.assertIn(kind, ("ran", "dead", "ran-noisy", "dead-noisy", "caution"))
                expected = kind.startswith("ran")
                self.assertEqual(ran, expected, "bash disagrees with the expectation: %r (%s)" % (text, other))
                if kind in ("ran", "dead"):
                    self.assertEqual(other, "", "bash was expected to stay silent: %r" % text)
                blocked = bool(g.find_violations(text))
                self.assertEqual(blocked, expected or kind == "caution", "guard verdict: %r" % text)
                if kind != "caution":
                    self.assertEqual(lexer_sees_a_substitution(text) and blocked, expected)

    def test_curated_cases_agree_with_bash(self):
        results = run_in_bash([text for _name, text, _ran in CURATED])
        for (name, text, expected), (ran, other) in zip(CURATED, results):
            with self.subTest(name=name):
                self.assertEqual(other, "", "the case itself failed in bash: %r" % text)
                self.assertEqual(ran, expected, "bash disagrees with the expectation: %r" % text)
                self.assertEqual(lexer_sees_a_substitution(text), expected, "the lexer disagrees: %r" % text)

    def test_every_live_backtick_case_is_blocked_and_every_dead_one_is_not(self):
        """실제로 도는 백틱은 기본 동작이 막고, 돌지 않는 글은 막지 않는다."""
        # 역슬래시가 접히는 글은 파일로 실행한 결과와 훅의 판정이 다를 수 있어 여기서는 뺀다
        judged = [(name, text, ran) for name, text, ran in CURATED
                  if "`" in text and g.fold_backslashes(text) == text]
        self.assertGreaterEqual(len(judged), 50)
        for name, text, ran in judged:
            with self.subTest(name=name):
                if ran:      # 이 목록에서 실제로 도는 글은 모두 백틱이 도는 글이다
                    self.assertTrue(g.find_violations(text), "a live backtick was not blocked: %r" % text)
                else:
                    self.assertEqual(g.find_violations(text), [])

    @unittest.skipUnless(os.name == "nt", "the backslash folding belongs to the Windows launcher")
    def test_fold_model_matches_a_real_launch(self):
        """파이썬이 bash.exe에 인자를 넘기는 방식은 Claude Code(node)와 같은 Windows 규약이다.
        그 경로로 넘긴 글이 fold_backslashes()의 결과와 같은지 본다."""
        payload = "\n".join(t for t, _r in MEASURED_FOLD if "\n" not in t)
        script = "while IFS= read -r line; do printf '%s\\n' \"$line\"; done <<'EOF'\n" + payload + "\nEOF"
        with tempfile.TemporaryDirectory(prefix="fold-check-") as tmp:
            env = {k: v for k, v in os.environ.items()
                   if k.upper() not in {"BASH_ENV", "ENV"} and not k.upper().startswith("BASH_FUNC_")}
            env.update(HOME=tmp, USERPROFILE=tmp)
            p = subprocess.run([BASH, "--noprofile", "--norc", "-c", script], capture_output=True,
                               timeout=60, cwd=tmp, env=env)
        got = p.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        self.assertEqual(got, g.fold_backslashes(payload) + "\n")


# ---- 무작위 대조 -------------------------------------------------------------------------------
SOUP = ["'", '"', "\\", "$", "{", "}", "#", ";", " ", " ", "\n", "x", "x", "`mark`", "`mark`", "$(mark)", "$(mark)",
        "$'", "${u:-", "$((", "))", "\\\\", ": <<E\n", ": <<'E'\n", "\nE\n",
        "(", ")", "[[ x =~ ", " ]]", "case x in ", "esac", "\r", "E)", "\\\nE\n", "${w//", "${w#", "/", "$[", "]", "<("]
FILL = ["`mark`", "$(mark)", "x", " ", "\\", "\\\\", "#", "'", '"', "$", ";", "\\`mark\\`", "\\$(mark)", "{", "}"]


def _fill(rng, exclude="", most=4):
    toks = [t for t in FILL if not any(ch in t for ch in exclude)]
    return "".join(rng.choice(toks) for _ in range(rng.randint(0, most)))


TEMPLATES = [
    lambda r: "echo '" + _fill(r, "'") + "'",
    lambda r: 'echo "' + _fill(r, '"') + '"',
    lambda r: "echo $'" + _fill(r, "'") + "'",
    lambda r: "echo " + _fill(r, "'\";"),
    lambda r: "echo x # " + _fill(r),
    lambda r: "echo x#" + _fill(r, "'\";"),
    lambda r: ": <<E\n" + _fill(r) + "\nE",
    lambda r: ": <<'E'\n" + _fill(r) + "\nE",
    lambda r: ": <<-E\n\t" + _fill(r) + "\n\tE",
    lambda r: ": <<\\E\n" + _fill(r) + "\nE",
    lambda r: 'echo "${u:-' + _fill(r, '"}') + '}"',
    lambda r: "echo ${u:-" + _fill(r, "'\"};# ") + "}",
    lambda r: "echo $(( 1 " + _fill(r, "'\"#;\\${}x") + "))",
    lambda r: "v=$(echo " + _fill(r, "'\"") + ")",
    lambda r: "( echo " + _fill(r, "'\"") + " )",
    lambda r: 'echo "a" \'b\' "' + _fill(r, '"') + "\" '" + _fill(r, "'") + "'",
    lambda r: "echo a \\\n" + _fill(r, "'\""),
    lambda r: 'echo "$(echo \'' + _fill(r, "'") + '\' "' + _fill(r, '"') + '")"',
    # w는 값이 있는 변수다(값이 비면 Bash가 무늬를 아예 펼치지 않는다)
    lambda r: 'echo "${w//' + _fill(r, '"}/') + '/}"',
    lambda r: 'echo "${w#' + _fill(r, '"}') + '}"',
    lambda r: 'echo "${w%\'' + _fill(r, "'") + '\'}"',
    lambda r: 'echo "${u:-\'' + _fill(r, "'") + '\'}"',
    lambda r: ": <<E\n$(echo '" + _fill(r, "'") + "')\nE",
    lambda r: 'v="$(: <<\'E\'\n' + _fill(r, "") + '\nE)"\necho "' + _fill(r, '"') + '"',
    lambda r: "[[ x =~ (" + _fill(r, "'\"()\\") + ") ]]; echo " + _fill(r, "'\";"),
    lambda r: ": <<E\n" + _fill(r) + " \\\nE\n" + _fill(r, "'") + "\nE",
    lambda r: ": <(echo " + _fill(r, "'\"") + ")#" + _fill(r, "'\";"),
]


def _may_skip_code(text):
    """case의 맞지 않는 갈래나 정의만 된 함수처럼, 실행되는 자리에 있어도 Bash가 건너뛸 수 있는 글인가.
    이런 글은 '검사기는 실행된다고 봤는데 돌지 않았다'를 오류로 치지 않는다."""
    # <( )는 따로 도는 프로세스라 읽는 쪽이 먼저 끝나면 안쪽 명령이 돌기 전에 끊긴다
    return "case " in text or "()" in text or "( )" in text or "<(" in text


def _soup_case(rng):
    return "".join(rng.choice(SOUP) for _ in range(rng.randint(1, 12)))


def _templated_case(rng):
    return "\n".join(rng.choice(TEMPLATES)(rng) for _ in range(rng.randint(1, 3)))


@unittest.skipUnless(BASH, "no usable bash (Git Bash) on this machine")
class RealBashRandomTests(unittest.TestCase):
    def test_random_cases_agree_with_bash(self):
        scale = max(1, int(os.environ.get("BASH_QUOTE_GUARD_FUZZ", "1") or "1"))
        rng = random.Random(int(os.environ.get("BASH_QUOTE_GUARD_FUZZ_SEED", "20261124")))
        cases = [_soup_case(rng) for _ in range(60 * scale)] + [_templated_case(rng) for _ in range(90 * scale)]
        cases = sorted(set(cases))
        results = run_in_bash(cases)
        missed, overcalled, clean = [], [], 0
        for text, (ran, other) in zip(cases, results):
            seen = lexer_sees_mark_run(text)
            if ran and not seen:
                missed.append(text)              # Bash는 실행했는데 검사기가 못 봤다: 가장 나쁜 경우
            elif not other:
                clean += 1                       # Bash가 군말 없이 끝낸 글만 반대 방향도 따진다
                if seen and not ran and not _may_skip_code(text):
                    overcalled.append(text)
        self.assertEqual(missed, [], "bash ran a substitution the lexer did not see")
        self.assertEqual(overcalled, [], "the lexer saw a substitution bash did not run")
        self.assertGreater(clean, len(cases) // 5, "too few cases ran cleanly for the comparison to mean anything")

if __name__ == "__main__":
    unittest.main()
