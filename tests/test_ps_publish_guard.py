"""PowerShell publishing policy, protocol, and timing regressions."""
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timing_limits import timing_limit

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
SCRIPT = os.path.join(SCRIPTS, "ps_publish_guard.py")
BT = "`"   # 시험 글 안의 백틱. 소스에 백틱을 흩지 않으려고 이름을 붙였다

sys.path.insert(0, SCRIPTS)
import ps_publish_guard as g  # noqa: E402

BLOCK = {
    "dq-notes": "gh release create v1 --notes \"use {b}widget{b} now\"",
    "bash-style-escape": "gh release create v1.2.3 --notes \"**\\{b}package.zip\\{b}** and \\{b}widget\\{b}\"",
    "dq-here-string": "$n = @\"\nUse {b}widget{b}.\n\"@\ngh release edit v1 --notes $n",
    "pr-body": "gh pr create --title \"t\" --body \"see {b}x{b}\"",
    "pr-merge-body": "gh pr merge 3 --rebase --body \"merged {b}main{b}\"",
    "issue-comment-bareword": "gh issue comment 5 --body a{b}nb",
    "git-commit": "git commit -m \"fix: handle {b}mode{b} key\"",
    "git-path-with-space": "git -C \"D:\\my repo\" commit -m \"a {b}b{b}\"",
    "git-config-then-tag": "git -c user.name=x tag -a v1 -m \"v1 {b}tag{b}\"",
    "gh-full-path": "& \"C:\\Program Files\\GitHub CLI\\gh.exe\" release create v1 --notes \"x {b}y{b}\"",
    "subexpression": "gh release create v1 --notes \"$(Get-Date) {b}n done\"",
    "nested-string-in-subexpression": "gh api repos/o/r -f body=\"$(\"a {b}b{b}\")\"",
    "smart-quotes": "gh release create v1 --notes \u201cuse {b}x{b}\u201d",
    "crlf-here-string": "$n = @\"\r\nUse {b}x{b}.\r\n\"@\r\ngh release create v1 --notes $n",
    # 하위 명령과 별칭(new = create). close·reopen은 -c/--comment로 글을 남긴다
    "release-new": "gh release new v1 --notes \"use {b}x{b} now\"",
    "pr-new": "gh pr new --title t --body \"see {b}x{b} now\"",
    "pr-close-c": "gh pr close 3 -c \"closing {b}x{b} now\"",
    "pr-close-comment": "gh pr close 3 --comment \"closing {b}x{b} now\"",
    "pr-reopen": "gh pr reopen 3 --comment \"back {b}x{b} now\"",
    "issue-new": "gh issue new --title t --body \"see {b}x{b} now\"",
    "issue-close-c": "gh issue close 5 -c \"fixed by {b}x{b} now\"",
    "issue-close-comment": "gh issue close 5 --comment \"fixed by {b}x{b} now\"",
    "issue-reopen": "gh issue reopen 5 -c \"again {b}x{b} now\"",
    "git-merge-m": "git merge --no-ff -m \"merge {b}feature{b} now\" feature",
    # 줄 이음·따옴표로 감싼 하위 명령 낱말·값을 따로 받는 git 옵션
    "continuation-gh-release": "gh {b}\n  release create v1 --notes \"use {b}x{b} now\"",
    "continuation-crlf-every-gap": "gh {b}\r\n  release {b}\r\n  create v1 --notes \"use {b}x{b} now\"",
    "continuation-git-options": "git -C D:/r {b}\n  -c user.name=x {b}\n  commit -m \"a {b}b{b} c\"",
    "quoted-subcommand-words": "gh \"release\" \"create\" v1 --notes \"use {b}x{b} now\"",
    "single-quoted-subcommand-words": "gh 'issue' 'comment' 5 --body \"see {b}x{b} now\"",
    "quoted-git-subcommand": "git \"commit\" -m \"a {b}b{b} c\"",
    "git-dir-separate-value": "git --git-dir D:/r/.git commit -m \"a {b}b{b} c\"",
    "git-dir-equals": "git --git-dir=D:/r/.git commit -m \"a {b}b{b} c\"",
    "git-work-tree-quoted": "git --work-tree \"D:/my tree\" --git-dir 'D:/r/.git' commit -m \"a {b}b{b} c\"",
    "git-namespace": "git --namespace ns tag -a v1 -m \"v1 {b}tag{b} now\"",
    "git-c-embedded-quotes": "git -c user.name=\"John Doe\" commit -m \"a {b}b{b} c\"",
    # 주석이 시작하는 자리(PowerShell 5.1 토큰과 대조)
    "comment-after-closing-quote": "Write-Output \"done\"# don't\ngh release create v1 --notes \"use {b}x{b} now\"",
    "hash-after-equals-is-text": "gh api repos/o/r/issues -f title=#42 -f body=\"use {b}x{b} now\"",
    "hash-after-string-inside-word": "gh api repos/o/r/issues -f body=\"see\"#42 -f title=\"{b}x{b} now\"",
    "hash-inside-bare-word": "gh release create v1 --notes a#b{b}x",
    "hash-after-bracket-inside-word": "gh api repos/o/r -f title=[x]#1 -f body=\"use {b}x{b} now\"",
    "bracket-word-in-argument": "gh issue create --label [x]#1 --body \"use {b}x{b} now\"",
    "comment-ends-at-lone-cr": "# done\rgh release create v1 --notes \"use {b}x{b} now\"",
    # 둥근 작은따옴표로 닫는 @'...'@ 뒤의 큰따옴표 게시
    "curly-single-here-closer": "$n = @'\nUse {b}x{b}.\n\u2019@\ngh release create v1 --notes \"use {b}y{b} now\"",
    # 간접 실행: 작은따옴표 안의 글이 코드로 실행된다
    "invoke-expression": "Invoke-Expression 'gh release create v1 --notes \"use {b}x{b} now\"'",
    "iex-pipe": "'gh pr comment 3 --body \"see {b}x{b} now\"' | iex",
    "powershell-c": "powershell -NoProfile -c 'git commit -m \"a {b}b{b} c\"'",
    "pwsh-command": "pwsh.exe -NoProfile -Command 'gh issue comment 5 --body \"see {b}x{b} now\"'",
    "iex-sq-here-string": "$c = @'\ngh release create v1 --notes \"use {b}x{b} now\"\n'@\nInvoke-Expression $c",
    "iex-nested": "iex 'iex ''gh release create v1 --notes \"use {b}x{b} now\"'''",
    # 저장소 옵션을 하위 명령 앞에 둔 꼴, 메시지 묶음 플래그, gh api 필드
    "gh-repo-before-release": "gh -R o/r release create v1 --notes \"use {b}x{b} now\"",
    "gh-repo-long-before-pr": "gh --repo=o/r pr create --title t --body \"see {b}x{b} now\"",
    "git-commit-am": "git commit -am \"fix {b}x{b} now\"",
    "gh-api-field": "gh api repos/o/r/issues -f title=t -f body=\"use {b}x{b} now\"",
    # -F 파일·-F - 로 넘기는 글을 같은 명령에서 큰따옴표로 채운 꼴,
    # 공백 없는 대입, 묶음 낱말 뒤나 붙여 쓴 -R, 붙여 쓴 gh api -f
    "commit-file-from-escape-in-same-command": "git commit -F msg.txt; Write-Output \"done{b}n\"",
    "commit-from-stdin": "\"fix {b}x{b} now\" | git commit -F -",
    "commit-from-here-string": "@\"\nfix {b}x{b} now\n\"@ | git commit -F -",
    "commit-file-written-here": "Set-Content msg.txt \"fix {b}x{b} now\"; git commit -F msg.txt",
    "tag-from-stdin": "\"v1 {b}x{b}\" | git tag -a v1 -F -",
    "notes-from-stdin": "\"n {b}x{b}\" | git notes add -F - HEAD",
    "api-input-stdin": "$j = @\"\n{\"body\":\"use {b}x{b} now\"}\n\"@\n$j | gh api repos/o/r/issues/1/comments --input -",
    "assignment-without-spaces-gh": "$r=gh release create v1 --notes \"use {b}x{b} now\"",
    "assignment-without-spaces-git": "$out=git commit -m \"fix {b}x{b} now\"",
    "repo-after-group": "gh release -R o/r create v1 --notes \"use {b}x{b} now\"",
    "repo-long-after-group": "gh pr --repo o/r comment 3 --body \"see {b}x{b} now\"",
    "repo-attached": "gh -Ro/r release create v1 --notes \"use {b}x{b} now\"",
    "api-field-attached": "gh api repos/o/r/issues -fbody=\"use {b}x{b} now\"",
    "commit-message-attached": "git commit -mfix{b}ed",
    "commit-long-option-prefix": "git commit --mess=\"fix {b}x{b}\"",
    "pr-merge-squash-body": "gh pr merge 3 --squash --body \"merged {b}x{b}\"",
}

ALLOW = {
    "notes-file": "gh release create v1 --notes-file notes.md --title \"v1\"",
    "single-quotes": "gh release create v1 --notes 'use {b}widget{b} now'",
    "sq-here-string": "$n = @'\nUse {b}widget{b}.\n'@\ngh release edit v1 --notes $n",
    "not-publishing": "Write-Output \"a{b}nb\"",
    "comment-only": "# note: {b}x{b}\ngh release create v1 --notes-file n.md",
    "block-comment": "<# {b}x{b} #>\ngit commit -F msg.txt",
    "line-continuation": "gh release create v1 {b}\n  --notes-file n.md",
    "line-continuation-crlf": "gh release create v1 {b}\r\n  --notes-file n.md",
    "release-view": "gh release view v1 --json body --jq '.body'",
    "git-log": "git log --format=\"%h {b}t %s\"",
    "doubled-single-quote": "git commit -m 'it''s {b}fine{b}'",
    "api-jq-in-single-quotes": "gh api repos/o/r/releases --jq '.[0].body | {b}x{b}'",
    "no-backtick-at-all": "git -C repo commit -F D:/x/msg.txt",
    "word-containing-gh": "Write-Output \"high{b}n\"; ghost release create",
    # 둥근 큰따옴표로 닫는 @"..."@ 뒤의 깨끗한 게시를 막지 않는다
    "curly-double-here-closer": "$n = @\"\nplain\n\u201d@\ngh release edit v1 --notes 'use {b}y{b}' --title $n",
    # 주석이 시작하는 자리
    "comment-after-closing-quote": "Write-Output \"done\"# it's {b}x{b}\ngh release create v1 --notes-file n.md",
    "comment-after-paren": "gh release create v1 --notes-file (Join-Path D:/x n.md)# {b}x{b} it's",
    "comment-after-index": "gh release create v1 --notes-file $files[0]# {b}x{b} it's",
    "comment-after-type-literal": "[void]# {b}x it's\ngh release create v1 --notes-file n.md",
    "comment-after-nbsp": "gh release create v1 --notes-file n.md\u00a0# {b}x{b} it's",
    "issue-close-then-comment": "gh issue close 5 # closing {b}x{b} later",
    "continuation-cr-only": "gh release create v1 {b}\r  --notes-file n.md",
    # 간접 실행이 있어도 안쪽이 안전한 꼴, 그리고 게시가 아닌 간접 실행
    "iex-inner-single-quotes": "iex 'gh release create v1 --notes ''use {b}x{b} now'''",
    "iex-inner-comment": "iex 'gh release create v1 --notes-file n.md # {b}x{b}'",
    "iex-not-publishing": "iex 'Write-Output \"a{b}nb\"'",
    # 글을 명령줄로 넘기지 않는 git·gh api는 다른 자리의 백틱 때문에 막지 않는다
    "git-tag-list-with-escape": "git tag --list \"v*\" | ForEach-Object { \"$_{b}t\" }",
    "git-merge-base": "git merge-base --is-ancestor a b; if ($?) { \"yes{b}n\" }",
    "git-merge-without-message": "git merge feature; \"merged{b}n\"",
    "gh-api-read-with-escape": "gh api repos/o/r/releases --jq '.[].tag_name' | ForEach-Object { \"tag: $_{b}n\" }",
    "git-notes-show": "git notes show HEAD; \"{b}n\"",
}


def _cases(table):
    return {name: text.replace("{b}", BT) for name, text in table.items()}


def _deep(levels):
    """'"$(' 를 levels번 겹친 PowerShell 식. 가장 안쪽 큰따옴표에 백틱이 있다."""
    return "Write-Output " + "\"$(" * levels + "\"a" + BT + "x\"" + ")\"" * levels


class DecisionTests(unittest.TestCase):
    def test_publishing_text_with_a_live_backtick_is_blocked(self):
        for name, command in _cases(BLOCK).items():
            with self.subTest(case=name):
                self.assertIsNotNone(g.find_problem(command), command)

    def test_safe_forms_pass(self):
        for name, command in _cases(ALLOW).items():
            with self.subTest(case=name):
                self.assertIsNone(g.find_problem(command), command)

    def test_backtick_positions_point_at_the_text(self):
        command = "gh release create v1 --notes \"a {b}b{b}\"".replace("{b}", BT)
        problem = g.find_problem(command)
        self.assertEqual([command[p] for p in problem.ticks], [BT, BT])
        self.assertEqual(len(problem.ticks), 2)
        self.assertFalse(problem.incomplete)
        self.assertFalse(problem.indirect)

    def test_indirect_positions_map_back_to_the_original(self):
        for name in ("invoke-expression", "iex-nested", "iex-sq-here-string"):
            with self.subTest(case=name):
                command = _cases(BLOCK)[name]
                problem = g.find_problem(command)
                self.assertTrue(problem.indirect)
                self.assertEqual([command[p] for p in problem.ticks], [BT, BT])
                self.assertEqual(command.index("\"use") + 5, problem.ticks[0])

    def test_message_names_the_fix(self):
        command = "gh release create v1 --notes \"a {b}b{b}\"".replace("{b}", BT)
        message = g.format_message(command, g.find_problem(command))
        self.assertIn("[backtick-check-hook]", message)
        self.assertIn("--notes-file", message)
        self.assertIn("--body-file", message)
        self.assertIn("git commit -F", message)
        self.assertIn("git tag -F", message)
        self.assertIn("1:", message)
        self.assertIn("5.1", message)
        self.assertIn("파일뿐", message)
        self.assertNotIn("작은따옴표로 넘겨도 된다", message)
        self.assertIn("따로 실행", message)

    def test_message_explains_indirect_evaluation(self):
        command = _cases(BLOCK)["invoke-expression"]
        self.assertIn("Invoke-Expression", g.format_message(command, g.find_problem(command)))

    def test_unterminated_input_does_not_raise(self):
        for command in ("gh release create v1 --notes \"a {b}", "git commit -m @\"\n{b}x", "gh pr create --body $(\"{b}",
                        "iex 'gh release create v1 --notes \"a {b}", "gh release create v1 --notes @'\n{b}"):
            with self.subTest(command=command):
                g.find_problem(command.replace("{b}", BT))   # 예외 없이 끝나기만 하면 된다

    def test_too_deep_to_scan_blocks_a_publish_command(self):
        command = "gh release create v1 --notes-file n.md\n" + _deep(600)
        problem = g.find_problem(command)
        self.assertIsNotNone(problem)
        self.assertTrue(problem.incomplete)
        message = g.format_message(command, problem)
        self.assertIn("너무 깊게 중첩", message)
        self.assertIn("끝까지 검사하지 못했다", message)

    def test_too_deep_without_publishing_passes(self):
        self.assertIsNone(g.find_problem(_deep(600)))

    def test_scanner_errors_block_only_publish_commands(self):
        def broken(*_args, **_kwargs):
            raise ValueError("scanner failure")
        with mock.patch.object(g, "_scan_code", broken):
            self.assertTrue(g.find_problem(_cases(ALLOW)["single-quotes"]).incomplete)
            self.assertIsNone(g.find_problem(_cases(ALLOW)["not-publishing"]))

    def test_publish_command_longer_than_the_read_limit_blocks(self):
        command = "gh release create v1 --notes-file n.md # " + "x" * g.MAX_LEN + BT
        self.assertTrue(g.find_problem(command).incomplete)


class TimingLimitTests(unittest.TestCase):
    def test_scale_is_one_by_default_and_accepts_positive_factors(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(timing_limit(0.5), 0.5)
            os.environ["BACKTICK_TIMING_SCALE"] = "3"
            self.assertEqual(timing_limit(2.0), 6.0)

    def test_invalid_scale_does_not_disable_time_checks(self):
        for value in ("", "bad", "nan", "inf", "-1", "0"):
            with self.subTest(value=value), mock.patch.dict(os.environ, BACKTICK_TIMING_SCALE=value):
                with self.assertRaisesRegex(ValueError, "finite positive"):
                    timing_limit(1.0)


class SpeedTests(unittest.TestCase):
    def test_option_runs_do_not_backtrack_exponentially(self):
        texts = ("git" + " --x" * 40 + " status",
                 "git" + " --git-dir -x" * 40 + " status",
                 "git -c " + "\"" * 81 + " status",
                 "git" + " -c \"\"\"\"" * 40 + " status",
                 "gh" + (" " + BT + "\n") * 40 + " status")
        for text in texts:
            with self.subTest(text=text[:24]):
                start = time.perf_counter()
                self.assertIsNone(g.PUBLISH.search(text))
                self.assertIsNone(g.find_problem(text + " " + BT + "x"))
                self.assertLess(time.perf_counter() - start, timing_limit(0.1))

    def test_crlf_line_continuations_do_not_backtrack(self):
        # A backtick + CRLF used to split two ways per continuation: 24 of them took 24 s, past the hook's 15 s.
        text = ("git" + (" " + BT + "\r\n  -x") * 30 + " " + BT + "\r\n  log\r\n"
                + "gh release create v1 --notes \"use " + BT + "x" + BT + " now\"")
        start = time.perf_counter()
        self.assertIsNotNone(g.find_problem(text))
        self.assertLess(time.perf_counter() - start, timing_limit(0.5))

    def test_git_inside_option_values_does_not_restart_the_search(self):
        # The search used to start again at every "git" inside --x=git, which grew with the square of the length.
        text = "git" + " --x=git" * 4000 + " status " + BT + "x"
        start = time.perf_counter()
        self.assertIsNone(g.find_problem(text))
        self.assertLess(time.perf_counter() - start, timing_limit(1.0))

    def test_many_publish_words_without_text_stay_linear(self):
        # Each match used to scan the rest of the command: 16,000 'git tag;' took 13.5 s.
        for text in ("git tag;" * 16000 + ' "' + BT + 'n"', "gh api x;" * 16000 + ' "' + BT + 'n"'):
            with self.subTest(text=text[:12]):
                start = time.perf_counter()
                g.find_problem(text)
                self.assertLess(time.perf_counter() - start, timing_limit(2.0))

    def test_git_value_options_holding_git_stay_bounded(self):
        # -c git, -C git: the search restarted at every inner git; 16,000 of them took over 40 s.
        for text in ("git" + " -c git" * 16000 + " status " + BT + "x", "git" + " -C git" * 16000 + " status " + BT + "x"):
            with self.subTest(text=text[:12]):
                start = time.perf_counter()
                g.find_problem(text)
                self.assertLess(time.perf_counter() - start, timing_limit(2.0))

    def test_long_match_is_shortened_in_the_message(self):
        command = "git" + " -c x" * 20 + ' commit -m "' + BT + 'x"'
        self.assertLess(len(g.format_message(command, g.find_problem(command))), 2000)

    def test_positions_count_cr_only_line_breaks(self):
        command = "Write-Output 1\rWrite-Output 2\rgh release create v1 --notes \"use " + BT + "x" + BT + " now\""
        self.assertIn("3:", g.format_message(command, g.find_problem(command)))


def _run(payload, *args):
    return subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", SCRIPT, *args],
                          input=payload, capture_output=True, timeout=30)


class EntryPointTests(unittest.TestCase):
    def payload(self, tool, command):
        return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                           "tool_input": {"command": command}}).encode("utf-8")

    def test_blocked_command_exits_with_the_block_code(self):
        command = _cases(BLOCK)["dq-notes"]
        proc = _run(self.payload("PowerShell", command), "--block-code=42")
        self.assertEqual(proc.returncode, 42, proc.stderr.decode("utf-8", "replace"))
        self.assertIn("[backtick-check-hook]", proc.stderr.decode("utf-8", "replace"))

    def test_default_block_code_is_2(self):
        proc = _run(self.payload("PowerShell", _cases(BLOCK)["git-commit"]))
        self.assertEqual(proc.returncode, 2)

    def test_other_tools_and_bad_input_pass(self):
        command = _cases(BLOCK)["dq-notes"]
        for payload in (self.payload("Bash", command), b"{not json", b"", json.dumps({"tool_name": "PowerShell"}).encode()):
            with self.subTest(payload=payload[:40]):
                self.assertEqual(_run(payload, "--block-code=42").returncode, 0)

    def test_clean_command_passes(self):
        proc = _run(self.payload("PowerShell", _cases(ALLOW)["notes-file"]), "--block-code=42")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, b"")

    def test_raw_mode(self):
        self.assertEqual(_run(_cases(BLOCK)["pr-body"].encode("utf-8"), "--raw").returncode, 2)

    def test_too_deep_publish_command_blocks_in_the_hook_process(self):
        command = "gh release create v1 --notes-file n.md\n" + _deep(600)
        proc = _run(self.payload("PowerShell", command), "--block-code=42")
        self.assertEqual(proc.returncode, 42, proc.stderr.decode("utf-8", "replace"))
        self.assertIn("끝까지 검사하지 못했다", proc.stderr.decode("utf-8", "replace"))
        proc = _run(self.payload("PowerShell", _deep(600)), "--block-code=42")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))

if __name__ == "__main__":
    unittest.main()
