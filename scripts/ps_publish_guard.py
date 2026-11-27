#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ps_publish_guard.py - PowerShell 명령 실행 전 검사 훅 (Claude Code·Codex·Antigravity 공용).

PowerShell interprets backticks in expandable strings and here-strings as escapes.
Write publishing text with a file-writing tool and pass its path to gh or git.

막는 것:
  gh로 글을 게시하는 명령(release create/new/edit, pr create/new/edit/comment/review/merge/close/reopen,
  issue create/new/edit/comment/close/reopen, api)이나 git으로 메시지를 쓰는 명령(commit, tag, notes,
  merge)이 코드 자리에 있을 때, 작은따옴표·@'...'@·주석·줄 이음 밖의 실행되는 백틱을 검사한다.
  1) 글을 넘기지 않는 명령은 제외한다:
     - git commit --no-edit(예: git commit --amend --no-edit) 또는 -C/--reuse-message (단, -m/-F/-e/-t·파이프가 없을 때)
     - 문장 경계 안에서 읽기·경량 전용인 명령: git tag -l/-d(주석 플래그 없음), git notes show/list/remove,
       git merge(-m/-F 없음), gh api(-f/-F/--input 없음).
     - 간접 실행 없이 문자열 리터럴·주석 안에만 글자로 적힌 게시 동사.
  2) 글이 인라인 인자로만 들어가면(-m/--message, --notes, --body, --title, --comment, 위치 인자, --notes=값,
     gh api -f 등) 그 게시 문장 안의 실행되는 백틱과, 그 게시 문장이 참조하는 같은 명령 안의 변수·하위식
     ($n, $(...))에 연결된 문장의 백틱만 막는다. 관계없는 다른 문장의 백틱("`t", Select-String "`r" 등)은 통과시킨다.
  3) 글이 파일이나 표준 입력으로 들어가면(-F 파일, -F -, --file, --notes-file, --body-file, --input, -t/--template,
     gh api -F, 앞쪽 파이프 |, 스플래팅 @var, $_/$PSItem/$args/$input, 동적 변수 설정 Set-Variable/function/param 등)
     같은 명령에서 그 파일·파이프·변수를 채웠을 수 있으므로 명령 전체 규칙을 유지한다.
  4) 간접 실행(Invoke-Expression, iex, powershell/pwsh -c/-Command, [scriptblock]::Create, InvokeScript,
     코드 자리의 문자열·변수·하위식 대상 호출 연산자 &)이 명령 어디에든 있으면 명령 전체 규칙을 유지한다
     (eval 계열은 작은따옴표·@'...'@ 본문도 코드로 한 번 더 읽고 원문 줄:칸으로 돌려 적는다).
  5) 끝까지 못 읽거나(중첩 과다 RecursionError, MAX_LEN 초과, 닫히지 않은 문자열·주석·괄호, 해석 실패)
     어느 문장에 속하는지 불확실하면 보수적으로 막는다.
  게시할 글은 파일 쓰기 도구로 파일에 쓰고 --notes-file·--body-file·-F 파일로 넘긴다.
  Windows PowerShell 5.1은 네이티브 프로그램에 넘기는 인자 안의 큰따옴표를 지우므로, 작은따옴표로 감싸
  넘기는 것도 안전하지 않다.

허용하는 것: 작은따옴표와 @'...'@ 안의 백틱(eval 간접 실행이 없으면 글자 그대로다), 주석(# 한 줄,
  <# ... #>), 줄 끝의 백틱(다음 줄로 잇기), 글을 넘기지 않는 명령의 백틱, 인라인 게시 문장과
  참조 변수에 연결되지 않은 별도 문장의 백틱.

주석과 히어스트링을 읽는 법:
  #과 <#은 토큰이 시작하는 자리에서만 주석을 연다. 명령 첫머리, 공백(NBSP·폼 피드·세로 탭 포함)과
  줄바꿈 뒤, ; | { ( & , 뒤, ) } 뒤, 토큰을 시작한 문자열·히어스트링의 닫는 따옴표 바로 뒤("done"# 주석),
  $변수 첨자($a[0])나 문장 첫머리 [형식]을 닫는 ] 뒤가 그 자리다. 따옴표 없는 낱말 안에서는 글자다:
  a#b, title=#42, body="x"#42(낱말 안 문자열의 뒤), a[1]#b, 인자 자리의 [abc]#c, a$(1)#c, a<#b.
  =는 낱말을 끊지 않는다. 한 줄 주석은 LF·CR 어느 쪽에서든 끝난다.
  @"·@'는 토큰 첫머리나 식 자리($x=@")에서만 히어스트링을 연다(인자 낱말 안의 x=@"는 보통 문자열이다).
  히어스트링은 줄 첫 칸의 따옴표+@로 닫히고 둥근 따옴표도 같은 종류로 친다: @"는 "“”„ 어느 것이든,
  @'는 '‘’‚‛ 어느 것이든 그 뒤에 @가 오면 닫힌다.
  어긋나는 자리(드물다): 식 자리에서 =·숫자·$변수 바로 뒤에 붙은 #($x=#c, 5#c, $a#b, $a.b#c)과
  -a:"x"#c의 #은 PowerShell에서 주석인데 여기서는 글자로 읽는다(더 막는 쪽). --% 뒤의 글은 PowerShell이
  그대로 넘기지만 여기서는 보통 인자로 읽는다(더 막는 쪽). 인자 자리에서 $ 바로 뒤의 <#($<#)은 글자인데
  블록 주석으로 읽는다($x=<# ... #>를 주석으로 읽으려는 것. 그 사이를 놓친다).

남는 틈 (이 검사기가 보지 못하는 것):
  앞선 명령에서 PowerShell 큰따옴표로 써 둔 노트 파일(--notes-file로 넘길 때는 이미 깨져 있다), .ps1
  파일 안의 명령, Bash 도구에서 띄운 PowerShell(powershell -c '...'), Start-Process, -EncodedCommand,
  변수에 숨긴 파일 플래그($flag="--notes-file" + 별도 파일 쓰기), 위 목록 밖의 gh·git 글쓰기
  (gh repo edit --description, gh secret set --body, git stash -m 등), 그리고 해당 훅이 호출되지 않는 실행 경로.
  PowerShell 파서와 동작이 다른 드문 꼴도 있다: 식 바로 뒤에 붙은 주석에 작은따옴표가 든 꼴($v = $base# it's)은
  그 뒤 줄을 문자열로 잘못 읽어 놓친다. -Command 없이 넘긴 powershell '...'(5.1은 -Command가 기본값),
  줄을 넘겨 쓴 -Command, 3단보다 깊은 iex, gh <# … #> release처럼 사이에 주석을 둔 꼴, git -C (식)처럼
  괄호 값을 둔 꼴, git tag·merge의 붙여 쓴 메시지(-mfix, --mess=), git commit-tree 같은 배관 명령도 보지 못한다.
  반대로 파일·표준 입력 게시(-F·--notes-file·--body-file·--input·앞쪽 파이프)와 함께 쓴 관계없는 이스케이프("`n"),
  참조 변수를 읽기 전용으로만 쓰는 다른 문장의 백틱은 보수적으로 막는다(게시 명령을 따로 실행하면 된다).
  파이썬 3.11 미만에서는 소유 한정자(++, *+) 대신 보통 한정자를 쓴다. 판정은 같지만 백틱+CRLF 줄 이음이 아주
  많은 명령에서는 느려질 수 있다.

동작: bash_quote_guard.py와 같다. 표준 입력으로 훅 JSON을 받는다. 막을 때는 표준 오류에 이유를 쓰고
  --block-code로 준 코드(기본 2)로 끝난다. 그 밖의 모든 경우와 이 스크립트 자신의 오류는 0이다
  (검사기 고장이 작업을 막지 않게 한다). 예외는 하나다: 게시 명령을 끝까지 읽지 못하면 위처럼 막는다.
  훅 명령은 42를 받아 그때만 2로 바꾼다.
  손으로 확인: python ps_publish_guard.py --raw < 명령.txt
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import json
import re
import sys
from collections import namedtuple

TOOL_NAMES = ("PowerShell",)
BT = "`"             # 백틱. 소스 곳곳에 백틱을 흩지 않으려고 이름을 붙였다
DQ = '"“”„'          # PowerShell은 둥근 큰따옴표도 큰따옴표로 읽는다
SQ = "'‘’‚‛"         # 둥근 작은따옴표도 마찬가지
MAX_LEN = 400_000    # 이보다 긴 명령은 앞부분만 읽는다(게시 명령이면 끝까지 못 읽은 것으로 본다)
MAX_INDIRECT = 3     # 작은따옴표 안을 코드로 다시 읽는 깊이(iex 'iex ''...''')
TOKEN_BREAK = " \t\r\n\f\v\u00a0;|{}()&,"   # 이 글자 뒤는 새 토큰의 첫머리다. =는 넣지 않는다(title=#42)
START, WORD, EXPR = 0, 1, 2   # 코드 자리의 상태: 토큰 첫머리 / 따옴표 없는 낱말 안 / $변수·[형식] 같은 식 토큰 안

Problem = namedtuple("Problem", "match ticks incomplete indirect")


class _ScanMeta:
    """_scan_code 한 번의 통과로 모은 구문 범위(주석·문자열·줄 이음·미닫힘 여부)."""
    __slots__ = ("non_code", "continuations", "unterminated")

    def __init__(self):
        self.non_code = []        # 정렬·비겹침 (start, end, kind): 'cm' | 'sq' | 'dq'
        self.continuations = []   # 정렬·비겹침 (start, end)
        self.unterminated = False


def _word(words):
    """하위 명령 낱말. 따옴표로 감싸도 된다("release" "create"). merge-base처럼 하이픈으로 이어진 낱말은 아니다."""
    return _Q + "?(?:" + words + r")(?![\w-])" + _Q + "?"


_Q = "[" + DQ + SQ + "]"                                   # 따옴표 한 글자(곧은 것·둥근 것)
# 소유 한정자(++, *+)는 파이썬 3.11부터다. 그보다 옛 파이썬에서는 보통 한정자로 대신한다(판정은 같고, 아래의
# 드문 입력에서 느려질 수 있을 뿐이다).
_PLUS, _STAR = ("++", "*+") if sys.version_info >= (3, 11) else ("+", "*")
# 공백·줄바꿈, 또는 줄 이음(줄 끝 백틱). 소유 한정자라 되짚지 않는다: 백틱+CRLF를 '백틱+CR'과 'LF'로도
# 나눌 수 있어, 줄 이음이 20개쯤 이어지면 검색 시간이 지수로 늘어 훅 제한 시간을 넘길 수 있다.
_SEP = r"(?:\s|" + BT + r"(?:\r\n?|\n))" + _PLUS
# 따옴표 문자열 하나. 겹친 따옴표("" '')는 글자이고, 닫는 따옴표 바로 뒤에는 같은 종류의 따옴표가 오지 않는다.
# 그래서 문자열을 나누는 방법이 하나뿐이다(되짚기가 지수로 늘지 않는다).
_DQS = ("[" + DQ + "](?:[^" + DQ + BT + "]|" + BT + r"[\s\S]|[" + DQ + "]{2})*"
        "[" + DQ + "](?![" + DQ + "])")
_SQS = "[" + SQ + "](?:[^" + SQ + "]|[" + SQ + "]{2})*[" + SQ + "](?![" + SQ + "])"
_ARG = "(?:[^" + r"\s" + DQ + SQ + BT + "]|" + BT + r"[^\r\n]|" + _DQS + "|" + _SQS + ")"   # 인자의 한 조각
# git 옵션. 값을 따로 받는 옵션(-c 값, --git-dir 값 ...)과 그 밖의 옵션(--x, --git-dir=값)을 서로 겹치지 않게
# 나눈다. 앞의 - 하나는 공통이다. 옛 꼴 --?[\w-]+는 --x를 두 가지로 나눌 수 있어 되짚기가 지수로 늘었다.
_GIT_VALUE_OPTS = "(?:c|-git-dir|-work-tree|-namespace|-config-env|-attr-source)"
_GIT_OPT = ("-(?:" + _GIT_VALUE_OPTS + _SEP + _ARG + _PLUS
            + "|(?!" + _GIT_VALUE_OPTS + r"(?:\s|" + BT + r"[\r\n]|$))" + _ARG + _STAR + ")")
# gh의 저장소 옵션은 하위 명령 앞이나 묶음 낱말 뒤에도 오고, 값을 붙여 쓸 수도 있다
# (gh -R o/r release create, gh release -R o/r create, gh --repo=o/r pr create, gh -Ro/r release create).
_GH_REPO = "(?:" + _SEP + "(?:-R|--repo)(?:" + _SEP + "|=)?" + _ARG + _PLUS + ")?"

# git 옵션 반복은 32개까지만 본다: 옵션 값 안의 git(-c git, --x=git)마다 검색이 다시 시작되어, 반복을 묶지
# 않으면 시간이 입력 길이의 제곱으로 늘 수 있다. 앞 글자 확인에는 =를 넣지 않는다($r=gh ...).
PUBLISH = re.compile(
    r"(?i)(?<![\w.$-])(?:gh(?:\.exe)?" + _Q + "?" + _GH_REPO + _SEP + "(?:"
    + _word("release") + _GH_REPO + _SEP + _word("create|new|edit")
    + "|" + _word("pr") + _GH_REPO + _SEP + _word("create|new|edit|comment|review|merge|close|reopen")
    + "|" + _word("issue") + _GH_REPO + _SEP + _word("create|new|edit|comment|close|reopen")
    + "|" + _word("api") + ")"
    + r"|git(?:\.exe)?" + _Q + "?(?:" + _SEP + _GIT_OPT + "){0,32}" + _SEP + _word("commit|tag|notes|merge") + ")"
)

# 글을 코드로 평가하는 간접 실행. 이것이 있으면 작은따옴표 안도 코드로 읽고, 명령 전체 규칙을 유지한다.
INDIRECT = re.compile(
    r"(?i)(?<![\w.$-])(?:invoke-expression|iex)(?![\w.-])"
    r"|(?<![\w.$-])(?:powershell|pwsh)(?:\.exe)?" + _Q + r"?[^\r\n;|]{0,300}?\s[-/]{1,2}"
    r"c(?:o(?:m(?:m(?:a(?:n(?:d(?:withargs)?)?)?)?)?)?|wa)?(?![\w-])"
    r"|\[\s*(?:system\.management\.automation\.)?scriptblock\s*\]\s*::\s*create(?![\w-])"
    r"|(?<![\w.-])executioncontext\s*\.\s*invokecommand\s*\.\s*invokescript(?![\w-])"
)

# 코드 자리의 호출 연산자 &가 문자열·변수·하위식을 호출하는 꼴(& "cmd", & 'cmd', & $cmd, & (...)).
# && 와 2>&1 리다이렉션은 제외한다. 이 꼴이 있으면 보수적으로 명령 전체 규칙을 유지한다.
_INDIRECT_CALL = re.compile(r"(?<![&>0-9*])&(?![&])[ \t]*(?:[" + DQ + SQ + r"]|\$|\()")

# 동적 변수 설정이나 함수·파라미터 바인딩(참조 변수가 있는 게시 명령에서 명령 전체 규칙으로 복귀).
_DYNAMIC_VAR_CONSTRUCT = re.compile(
    r"(?i)(?<![\w.-])(?:set-variable|sv|new-variable|nv|tee-object|function|filter|param)(?![\w.-])"
    r"|(?<![\w-])-(?:outvariable|ov|errorvariable|ev|informationvariable|iv|variable)(?![\w-])"
)

_VAR_RE = re.compile(
    r"(?i)\$(?:\{(?:(?:global|local|script|private|using|workflow|variable):)?([^}]+)\}"
    r"|(?:(?:global|local|script|private|using|workflow|variable):)?(env:[A-Za-z_]\w*|[A-Za-z_]\w*))"
)
_SPECIAL_FLOW_VARS = frozenset(("_", "psitem", "args", "input", "matches"))
_BUILTIN_CONST_VARS = frozenset(("true", "false", "null"))
_SPLAT_RE = re.compile(r"^@[A-Za-z_][\w:]*$")
_SHORT_FILE_FLAG = re.compile(r"^-[a-zA-Z]*F")
_CONT_WORD_OPS = frozenset((
    "-f", "-join", "-split", "-replace", "-creplace", "-ireplace",
    "-csplit", "-isplit", "-and", "-or", "-xor", "-band", "-bor", "-bxor",
    "-shl", "-shr", "-as", "-is", "-isnot",
))

_EOL = re.compile(r"[\r\n]")
_SQ_CHAR = re.compile("[" + SQ + "]")
_HERE_CLOSE = {True: re.compile("[\r\n][" + DQ + "]@"), False: re.compile("[\r\n][" + SQ + "]@")}
_CONTINUATION = re.compile(BT + r"(?:\r\n?|\n)")


def _sq_end(text, i):
    """작은따옴표 문자열(text[i]가 여는 따옴표)의 (본문 끝, 닫는 따옴표 다음 위치). ''는 따옴표 글자다."""
    n = len(text)
    m = _SQ_CHAR.search(text, i + 1)
    while m:
        j = m.start()
        if j + 1 < n and text[j + 1] in SQ:
            m = _SQ_CHAR.search(text, j + 2)
            continue
        return j, j + 1
    return n, n


def _here_body(text, i):
    """i가 @" 또는 @'의 @이면, 여는 표지 뒤에 공백만 있고 줄이 끝나는지 본다. 본문 시작 위치(아니면 -1).
    줄바꿈은 LF·CRLF·CR 모두 된다."""
    n = len(text)
    j = i + 2
    while j < n and text[j] in " \t":
        j += 1
    if text.startswith("\r\n", j):
        return j + 2
    if j < n and text[j] in "\r\n":
        return j + 1
    return -1


def _here_end(text, body, double):
    """here-string 본문의 끝을 찾는다. 닫는 표지(따옴표 + @)는 줄의 첫 칸에 오고, 따옴표는 같은 종류면
    곧은 것이든 둥근 것이든 된다. (본문 끝, 표지 다음)."""
    quotes = DQ if double else SQ
    if body + 1 < len(text) and text[body] in quotes and text[body + 1] == "@":
        return body, body + 2
    m = _HERE_CLOSE[double].search(text, body)
    if m is None:
        return len(text), len(text)
    return m.start(), m.end()


def _scan_dq(text, i, out, sq, meta=None, open_pos=None):
    """큰따옴표 문자열 안(i는 여는 따옴표 다음)을 읽는다. 백틱을 모으고 닫는 따옴표 다음 위치를 돌려준다.
    $( ... ) 안은 코드라 그 안의 문자열도 같은 규칙으로 본다."""
    n = len(text)
    seg = open_pos if open_pos is not None else i
    while i < n:
        c = text[i]
        if c == BT:
            out.append(i)
            i += 2
            continue
        if c in DQ:
            if i + 1 < n and text[i + 1] in DQ:
                i += 2
                continue
            if meta is not None:
                meta.non_code.append((seg, i + 1, "dq"))
            return i + 1
        if c == "$" and text.startswith("$(", i):
            if meta is not None and i > seg:
                meta.non_code.append((seg, i, "dq"))
            i = _scan_code(text, i + 2, out, sq, stop_at_paren=True, meta=meta)
            seg = i
            continue
        i += 1
    if meta is not None:
        if n > seg:
            meta.non_code.append((seg, n, "dq"))
        meta.unterminated = True
    return n


def _scan_here_dq_with_subexpr(text, open_pos, body, body_end, after, out, sq, meta):
    """$( ... )가 든 @"..."@ 본문을 읽어 백틱을 모으고, $( ... ) 바깥만 non_code('dq')로 기록한다."""
    if meta is not None:
        meta.non_code.append((open_pos, body, "dq"))
    j = body
    seg = body
    while j < body_end:
        c = text[j]
        if c == BT:
            out.append(j)
            j += 2 if j + 1 < body_end else 1
            continue
        if c == "$" and text.startswith("$(", j) and j + 2 <= body_end:
            if meta is not None and j > seg:
                meta.non_code.append((seg, j, "dq"))
            nxt = _scan_code(text, j + 2, out, sq, stop_at_paren=True, meta=meta)
            if nxt > body_end:
                if meta is not None:
                    meta.unterminated = True
                return
            j = nxt
            seg = j
            continue
        j += 1
    if meta is not None and seg < after:
        meta.non_code.append((seg, after, "dq"))


def _scan_code(text, i, out, sq, stop_at_paren=False, meta=None):
    """코드 자리를 읽는다. 작은따옴표·주석·줄 이음 밖의 백틱 위치를 out에, 작은따옴표 문자열과 @'...'@
    본문의 자리를 sq에 모은다. stop_at_paren이면 짝이 맞는 닫는 괄호 다음 위치에서 멈춘다($( ) 안).
    state는 #이 주석을 여는지 정한다: 토큰 첫머리(START)에서만 연다. cmd_pos는 문장 첫머리인지다:
    거기서 [로 시작하는 토큰은 [형식](식)이고, 인자 자리의 [abc]는 따옴표 없는 낱말이다."""
    n = len(text)
    depth = 1
    state = START
    cmd_pos = True
    while i < n:
        c = text[i]
        if c == "#":
            if state == START:                 # 줄 끝까지 주석
                m = _EOL.search(text, i)
                end = n if m is None else m.start()
                if meta is not None:
                    meta.non_code.append((i, end, "cm"))
                i = end
                continue
            i += 1                             # 낱말 안의 #은 글자다(a#b, title=#42)
            continue
        if c == "<" and state != WORD and text.startswith("<#", i):
            end = text.find("#>", i + 2)
            if end < 0:
                if meta is not None:
                    meta.non_code.append((i, n, "cm"))
                    meta.unterminated = True
                i = n
            else:
                if meta is not None:
                    meta.non_code.append((i, end + 2, "cm"))
                i = end + 2
            state = START
            continue
        if c == "@" and state != WORD and i + 1 < n and (text[i + 1] in DQ or text[i + 1] in SQ):
            body = _here_body(text, i)
            if body >= 0:
                double = text[i + 1] in DQ
                body_end, after = _here_end(text, body, double)
                unclosed = body_end == after
                if double:
                    if "$(" in text[body:body_end]:
                        _scan_here_dq_with_subexpr(text, i, body, body_end, after, out, sq, meta)
                    else:
                        k = text.find(BT, body, body_end)
                        while k >= 0:
                            out.append(k)
                            k = text.find(BT, k + 1, body_end)
                        if meta is not None:
                            meta.non_code.append((i, after, "dq"))
                else:
                    sq.append((body, body_end, False))
                    if meta is not None:
                        meta.non_code.append((i, after, "sq"))
                if unclosed and meta is not None:
                    meta.unterminated = True
                i = after
                state = START                  # 닫는 표지 바로 뒤의 #은 주석이다
                cmd_pos = False
                continue
        if c in SQ:                            # 낱말 안의 문자열이면 낱말이 이어지고, 토큰 첫머리면 문자열이
            body_end, after = _sq_end(text, i)  # 토큰이라 닫는 따옴표 뒤가 다시 첫머리다. 둘 다 state 그대로
            sq.append((i + 1, body_end, True))
            if meta is not None:
                meta.non_code.append((i, after, "sq"))
                if body_end == after:
                    meta.unterminated = True
            i = after
            cmd_pos = False
            continue
        if c in DQ:
            i = _scan_dq(text, i + 1, out, sq, meta=meta, open_pos=i)
            cmd_pos = False
            continue
        if c == BT:
            if text.startswith("\n", i + 1) or text.startswith("\r", i + 1):
                step = 3 if text.startswith("\r\n", i + 1) else 2   # 줄 이음
                if meta is not None:
                    meta.continuations.append((i, i + step))
                i += step
                state = START
                continue
            out.append(i)
            i += 2
            if state == START:
                state = WORD
            cmd_pos = False
            continue
        if c == "$" and text.startswith("$(", i):
            i = _scan_code(text, i + 2, out, sq, stop_at_paren=True, meta=meta)
            if state != WORD:                  # 낱말 안의 $( )는 낱말을 끊지 않는다(a$(1)#c의 #은 글자)
                state = START
            cmd_pos = False
            continue
        if stop_at_paren:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
        if c in TOKEN_BREAK:
            state = START
            if c in "\r\n;|{(&":
                cmd_pos = True
            elif c in "),}":
                cmd_pos = False
        elif c == "]":
            if state != WORD:                  # $a[0]·[int]을 닫는 ]. 낱말 안(a[1]#b)에서는 글자다
                state = START
            cmd_pos = False
        elif state == START:
            if c == "[":                       # 문장 첫머리나 ) ] 바로 뒤의 [는 식이고, 인자 자리의 [abc]는 낱말이다
                state = EXPR if cmd_pos or text[i - 1:i] in (")", "]") else WORD
            else:
                state = EXPR if c == "$" else WORD
            cmd_pos = c == "="                 # 홀로 선 =(대입) 뒤는 다시 문장 첫머리다
        i += 1
    if stop_at_paren and meta is not None:
        meta.unterminated = True
    return n


def live_backticks(text):
    """작은따옴표·주석·줄 이음 밖에 있는 백틱의 위치를 모은다(큰따옴표·@"..."@·따옴표 없는 자리)."""
    out = []
    _scan_code(text[:MAX_LEN], 0, out, [])
    return out


def _unquote_sq(text, start, end, doubled):
    """작은따옴표 문자열 본문 text[start:end]에서 ''를 '로 푼다. (풀린 글, 글자마다 원래 위치)."""
    if not doubled:
        return text[start:end], list(range(start, end))
    chars, where = [], []
    k = start
    while k < end:
        chars.append(text[k])
        where.append(k)
        k += 2 if text[k] in SQ and k + 1 < end and text[k + 1] in SQ else 1
    return "".join(chars), where


def _code_in_sq(text, spans, where, level):
    """작은따옴표 문자열 본문을 코드로 읽어 백틱 위치를 원문 위치로 모은다(Invoke-Expression 'gh ... "..."' 꼴).
    where는 text의 글자마다 원문 위치(맨 바깥에서는 None)."""
    found = []
    for start, end, doubled in spans:
        body, pos = _unquote_sq(text, start, end, doubled)
        if where is not None:
            pos = [where[p] for p in pos]
        inner_out, inner_sq = [], []
        _scan_code(body, 0, inner_out, inner_sq)
        found.extend(pos[p] for p in inner_out)
        if inner_sq and level < MAX_INDIRECT and INDIRECT.search(body):
            found.extend(_code_in_sq(body, inner_sq, pos, level + 1))
    return found


def _find_ticks_with_meta(text):
    """(정렬된 백틱 위치 목록, 간접 실행 때문에 새로 찾은 것이 있는지, eval 간접 실행 존재 여부, _ScanMeta)."""
    out, sq = [], []
    meta = _ScanMeta()
    _scan_code(text, 0, out, sq, meta=meta)
    found = set(out)
    has_indirect_eval = bool(INDIRECT.search(text))
    indirect_extra = False
    if sq and has_indirect_eval:
        extra = set(_code_in_sq(text, sq, None, 1)) - found
        indirect_extra = bool(extra)
        found |= extra
    return sorted(found), indirect_extra, has_indirect_eval, meta


def _find_ticks(text):
    """(백틱 위치 목록, 간접 실행 때문에 새로 찾은 것이 있는지). 위치는 원문 기준으로 정렬한다."""
    ticks, indirect, _, _ = _find_ticks_with_meta(text)
    return ticks, indirect


CARRY_WINDOW = 4000  # 예외 시 보수 판정 범위(글자). 일치마다 끝까지 읽으면 시간이 제곱으로 는다
_VERB = re.compile(r"(?i)(commit|tag|notes|merge|api)" + _Q + "?$")
# git tag: 주석 태그를 만드는 꼴(-a -s -m -F -u, 묶음 -am 포함, 긴 이름도)만 글을 받는다. 나머지(-l, -d, 경량 태그)는 읽기다.
_TAG_TEXT = re.compile(r"(?<![\w-])(?:-[a-zA-Z]*[asmFu](?![a-zA-Z])|--(?:annotate|sign|message|file|local-user)(?![\w-]))")
# git notes: add·append·edit·copy만 글을 받는다(show·list·remove는 읽기·지우기).
_NOTES_TEXT = re.compile(r"(?i)(?<![\w-])(?:add|append|edit|copy)(?![\w-])")
# git merge: -m·-F(묶음 포함)·--message·--file이 있을 때만 글을 받는다(없으면 기본 메시지).
_MERGE_TEXT = re.compile(r"(?<![\w-])(?:-[a-zA-Z]*[mF](?![a-zA-Z])|--(?:message|file)(?![\w-]))")
# gh api: 필드(-f, -F, 붙여 쓴 -fbody=...)나 --input이 있을 때만 글을 보낸다(--jq만 있는 읽기는 아니다).
_API_TEXT = re.compile(r"(?<![\w-])(?:-[fF]|--field(?![\w-])|--raw-field(?![\w-])|--input(?![\w-]))")


def _carries_text(command, m):
    """예외·폴백 시 쓰는 보수적 판정(구문 파싱 전). 정상 경로는 문장 단위 토큰으로 더 정확히 판정한다."""
    text = m.group(0)
    verb = _VERB.search(text)
    if not verb:
        return True
    rest = command[m.end():m.end() + CARRY_WINDOW]
    word = verb.group(1).lower()
    if text[:2].lower() == "gh":   # gh: api만 따로 본다(gh pr merge --body는 늘 글을 넘긴다)
        return word != "api" or bool(_API_TEXT.search(rest))
    if word == "tag":
        return bool(_TAG_TEXT.search(rest))
    if word == "notes":
        return bool(_NOTES_TEXT.search(rest))
    if word == "merge":
        return bool(_MERGE_TEXT.search(rest))
    if word == "api":
        return bool(_API_TEXT.search(rest))
    return True


def _span_containing(spans, starts, pos):
    """정렬·비겹침 spans[(s, e, ...)] 중 s <= pos < e 인 항목을 반환(없으면 None)."""
    idx = bisect_right(starts, pos) - 1
    if idx >= 0 and pos < spans[idx][1]:
        return spans[idx]
    return None


def _enclosed_in_non_code(non_code, nc_starts, start, end):
    """[start, end) 전체가 단일 문자열·주석 범위 안에 완전히 갇혀 있는지."""
    span = _span_containing(non_code, nc_starts, start)
    return span is not None and end <= span[1]


def _has_code_match(pattern, text, non_code, nc_starts):
    """non_code(문자열·주석) 바깥의 코드 자리에서 pattern이 일치하는지."""
    for m in pattern.finditer(text):
        if _span_containing(non_code, nc_starts, m.start()) is None:
            return True
    return False


def _unquote_flag_token(tok):
    """단순 따옴표로 감싼 플래그 낱말("-F", '--no-edit')의 바깥 따옴표를 벗긴다."""
    if len(tok) >= 2 and ((tok[0] in DQ and tok[-1] in DQ) or (tok[0] in SQ and tok[-1] in SQ)):
        inner = tok[1:-1]
        if not any(ch in DQ or ch in SQ for ch in inner):
            return inner
    return tok


_MATCH_CLOSE = {"(": ")", "{": "}", "[": "]"}


def _build_match_closers(text, non_code, continuations):
    """코드 자리의 짝 맞는 (, {, [ 의 닫는 위치를 한 번의 선형 통과로 기록한다."""
    n = len(text)
    closers = {}
    stack = []
    i = 0
    nc_idx = 0
    ct_idx = 0
    while i < n:
        while nc_idx < len(non_code) and non_code[nc_idx][1] <= i:
            nc_idx += 1
        if nc_idx < len(non_code) and non_code[nc_idx][0] <= i:
            i = non_code[nc_idx][1]
            continue
        while ct_idx < len(continuations) and continuations[ct_idx][1] <= i:
            ct_idx += 1
        if ct_idx < len(continuations) and continuations[ct_idx][0] <= i:
            i = continuations[ct_idx][1]
            continue
        c = text[i]
        if c in "({[":
            stack.append((c, i))
        elif c in ")}]":
            if stack and _MATCH_CLOSE[stack[-1][0]] == c:
                _, open_pos = stack.pop()
                closers[open_pos] = i
        i += 1
    return closers


def _publish_stmt_end_and_tokens(text, start, non_code, nc_starts, continuations, cont_starts, closers):
    """게시 명령 m.end()(=start)부터 해당 문장 끝까지 읽고 (stmt_end, tokens, nested_spans, ambiguous)를 반환한다.
    균형 잡힌 ( ... )·{ ... }·[ ... ] 는 closers로 O(1)에 건너뛰어 중첩 입력에서도 선형 시간을 유지한다."""
    n = len(text)
    i = start
    nc_idx = bisect_left(nc_starts, start)
    if nc_idx > 0 and non_code[nc_idx - 1][1] > start:
        nc_idx -= 1
    ct_idx = bisect_left(cont_starts, start)
    if ct_idx > 0 and continuations[ct_idx - 1][1] > start:
        ct_idx -= 1

    last_sig = ""
    tokens = []
    nested_spans = []
    tok_start = -1
    ambiguous = False

    def flush_tok(pos):
        nonlocal tok_start
        if tok_start >= 0:
            tokens.append(text[tok_start:pos])
            tok_start = -1

    while i < n:
        while nc_idx < len(non_code) and non_code[nc_idx][1] <= i:
            nc_idx += 1
        if nc_idx < len(non_code) and non_code[nc_idx][0] <= i:
            _, ne, kind = non_code[nc_idx]
            if kind == "cm":
                flush_tok(i)
            else:
                if tok_start < 0:
                    tok_start = i
                last_sig = '"'
            i = ne
            continue

        while ct_idx < len(continuations) and continuations[ct_idx][1] <= i:
            ct_idx += 1
        if ct_idx < len(continuations) and continuations[ct_idx][0] <= i:
            flush_tok(i)
            i = continuations[ct_idx][1]
            continue

        c = text[i]
        if c in " \t\f\v\u00a0":
            flush_tok(i)
            i += 1
            continue

        if c in ";|" or (c == "&" and not (i > 0 and text[i - 1] == ">")):
            break
        if c in ")}]":
            break
        if c in "\r\n":
            if last_sig == ",":
                flush_tok(i)
                i += 1
                continue
            break

        if c in "({[":
            close_pos = closers.get(i)
            if close_pos is None:
                ambiguous = True
                break
            if tok_start < 0:
                tok_start = i
            nested_spans.append((i, close_pos + 1))
            last_sig = _MATCH_CLOSE[c]
            i = close_pos + 1
            if nc_idx < len(non_code) and non_code[nc_idx][0] < i:
                nc_idx = bisect_left(nc_starts, i)
                if nc_idx > 0 and non_code[nc_idx - 1][1] > i:
                    nc_idx -= 1
            if ct_idx < len(continuations) and continuations[ct_idx][0] < i:
                ct_idx = bisect_left(cont_starts, i)
                if ct_idx > 0 and continuations[ct_idx - 1][1] > i:
                    ct_idx -= 1
            continue

        if tok_start < 0:
            tok_start = i
        last_sig = c
        i += 1

    flush_tok(i)
    return i, tokens, nested_spans, ambiguous


def _is_piped_in(text, match_start, non_code, nc_starts, continuations, cont_starts):
    """게시 명령 바로 앞이 파이프(|, || 제외)인지 확인한다(줄바꿈 뒤 파이프 이어쓰기 포함)."""
    j = match_start
    # & "C:\...\gh.exe" release create 처럼 match_start가 따옴표 경로 안이면 여는 따옴표 앞까지 물러선다
    span = _span_containing(non_code, nc_starts, match_start)
    if span is not None:
        j = span[0]
    j -= 1
    saw_newline = False
    while j >= 0:
        span = _span_containing(non_code, nc_starts, j)
        if span is not None:
            if span[2] == "cm":
                j = span[0] - 1
                continue
            return False
        cspan = _span_containing(continuations, cont_starts, j)
        if cspan is not None:
            j = cspan[0] - 1
            continue
        c = text[j]
        if c in " \t\f\v\u00a0":
            j -= 1
            continue
        if c in "\r\n":
            saw_newline = True
            j -= 1
            continue
        if not saw_newline and c in "&." and not (j > 0 and text[j - 1] == c):
            j -= 1
            continue
        if c == "|":
            return not (j > 0 and text[j - 1] == "|")
        return False
    return False


def _git_short_flags(tok):
    """git 단일 대시 묶음 플래그를 해석해 (has_msg, has_file, has_edit, has_reuse)를 반환한다."""
    has_msg = has_file = has_edit = has_reuse = False
    for ch in tok[1:]:
        if ch == "m":
            has_msg = True
            break
        if ch in "Ft":
            has_file = True
            break
        if ch == "c":
            has_edit = True
            break
        if ch == "e":
            has_edit = True
            continue
        if ch == "C":
            has_reuse = True
            break
        if ch in "uS":
            break
        if not ch.isalpha():
            break
    return has_msg, has_file, has_edit, has_reuse


def _classify_publish(m, tokens, piped_in):
    """게시 명령 하나를 분석해 (carries_text, needs_whole_command)를 반환한다."""
    matched = m.group(0)
    verb_m = _VERB.search(matched)
    is_gh = matched[:2].lower() == "gh"
    word = verb_m.group(1).lower() if verb_m else ""

    has_splat = any(_SPLAT_RE.match(t) for t in tokens)
    if has_splat:
        return True, True

    # '--' 이전의 옵션 토큰만 플래그로 해석한다
    opt_tokens = []
    for raw in tokens:
        t = _unquote_flag_token(raw)
        if t == "--":
            break
        opt_tokens.append(t)

    if not is_gh and word == "commit":
        has_msg = has_file = has_edit = has_reuse = has_no_edit = False
        for t in opt_tokens:
            if t.startswith("--"):
                opt = t.split("=", 1)[0].lower()
                if opt == "--no-edit":
                    has_no_edit = True
                elif opt == "--reuse-message":
                    has_reuse = True
                elif opt.startswith("--m") and "--message".startswith(opt):
                    has_msg = True
                elif opt.startswith("--fi") and "--file".startswith(opt):
                    has_file = True
                elif opt.startswith("--te") and "--template".startswith(opt):
                    has_file = True
                elif opt in ("--edit", "--reedit-message", "--fixup") or (
                    len(opt) >= 4 and "--edit".startswith(opt)
                ):
                    has_edit = True
            elif t.startswith("-") and len(t) > 1:
                m1, f1, e1, r1 = _git_short_flags(t)
                has_msg |= m1
                has_file |= f1
                has_edit |= e1
                has_reuse |= r1
        if (has_no_edit or has_reuse) and not (has_msg or has_file or has_edit or piped_in):
            return False, False
        return True, bool(has_file or piped_in or (has_edit and not has_msg))

    if not is_gh and word == "tag":
        joined = " ".join(opt_tokens)
        if not _TAG_TEXT.search(joined):
            return False, False
        has_file = any(
            (t.startswith("--") and t.split("=", 1)[0].lower().startswith("--fi")
             and "--file".startswith(t.split("=", 1)[0].lower()))
            or bool(_SHORT_FILE_FLAG.match(t))
            for t in opt_tokens
        )
        return True, bool(has_file or piped_in)

    if not is_gh and word == "notes":
        if not any(_NOTES_TEXT.fullmatch(t) for t in opt_tokens):
            return False, False
        has_file = any(
            (t.startswith("--") and t.split("=", 1)[0].lower().startswith("--fi")
             and "--file".startswith(t.split("=", 1)[0].lower()))
            or bool(_SHORT_FILE_FLAG.match(t))
            for t in opt_tokens
        )
        return True, bool(has_file or piped_in)

    if not is_gh and word == "merge":
        joined = " ".join(opt_tokens)
        if not _MERGE_TEXT.search(joined):
            return False, False
        has_file = any(
            (t.startswith("--") and t.split("=", 1)[0].lower().startswith("--fi")
             and "--file".startswith(t.split("=", 1)[0].lower()))
            or bool(_SHORT_FILE_FLAG.match(t))
            for t in opt_tokens
        )
        return True, bool(has_file or piped_in)

    if is_gh and word == "api":
        joined = " ".join(opt_tokens)
        if not _API_TEXT.search(joined):
            return False, False
        has_file = False
        for t in opt_tokens:
            if t.startswith("--"):
                opt = t.split("=", 1)[0].lower()
                if opt in ("--input", "--field"):
                    has_file = True
            elif t.startswith("-F"):
                has_file = True
        return True, bool(has_file or piped_in)

    # gh release / pr / issue
    has_file = False
    for t in opt_tokens:
        if t.startswith("--"):
            opt = t.split("=", 1)[0].lower()
            if opt in ("--notes-file", "--body-file", "--file"):
                has_file = True
        elif _SHORT_FILE_FLAG.match(t):
            has_file = True
    return True, bool(has_file or piped_in)


def _extract_vars(text, start, end, non_code, nc_starts):
    """[start, end) 안의 코드·큰따옴표·@"..."@ 자리에서 참조되는 PowerShell 변수 이름을 소문자 집합으로 모은다.
    작은따옴표·@'...'@·주석 안의 $var는 확장되지 않으므로 제외한다."""
    vars_found = set()
    nc_idx = bisect_left(nc_starts, start)
    if nc_idx > 0 and non_code[nc_idx - 1][1] > start:
        nc_idx -= 1
    pos = start
    while pos < end:
        while nc_idx < len(non_code) and non_code[nc_idx][1] <= pos:
            nc_idx += 1
        if nc_idx < len(non_code) and non_code[nc_idx][0] <= pos:
            ns, ne, kind = non_code[nc_idx]
            seg_end = min(ne, end)
            if kind == "dq":
                for vm in _VAR_RE.finditer(text, pos, seg_end):
                    name = (vm.group(1) or vm.group(2)).strip().lower()
                    if name and name not in _BUILTIN_CONST_VARS:
                        vars_found.add(name)
            pos = seg_end
            continue
        seg_end = min(end, non_code[nc_idx][0]) if nc_idx < len(non_code) else end
        for vm in _VAR_RE.finditer(text, pos, seg_end):
            name = (vm.group(1) or vm.group(2)).strip().lower()
            if name and name not in _BUILTIN_CONST_VARS:
                vars_found.add(name)
        pos = seg_end
    return vars_found


def _statement_spans(text, non_code, nc_starts, continuations, cont_starts):
    """변수 흐름 추적용 문장 범위 목록 [(start, end), ...]을 한 번의 선형 통과로 뽑는다.
    { ... }뿐 아니라 다중 문장을 담는 $( ... )·@( ... ) 안도 문장 단위로 분리하며,
    $n = if (...) { ... } / $n = $(...) 같은 대입 식은 바깥 대입 문장 범위로도 포함한다."""
    n = len(text)
    spans = []

    def emit(s, e):
        while s < e and text[s] in " \t\r\n\f\v\u00a0":
            s += 1
        while e > s and text[e - 1] in " \t\r\n\f\v\u00a0":
            e -= 1
        if s < e:
            spans.append((s, e))

    i = 0
    nc_idx = 0
    ct_idx = 0
    stmt_start = 0
    first_char = ""
    has_assign = False
    paren = bracket = 0
    block_stack = []   # (outer_start, outer_first, outer_assign, closer_char, outer_paren, outer_bracket)
    last_sig = ""
    cur_word = []
    last_word = ""

    def reset_stmt(pos):
        nonlocal stmt_start, first_char, has_assign, last_word
        stmt_start = pos
        first_char = ""
        has_assign = False
        cur_word.clear()
        last_word = ""

    def finish_word():
        nonlocal last_word
        if cur_word:
            last_word = "".join(cur_word).lower()
            cur_word.clear()

    while i < n:
        while nc_idx < len(non_code) and non_code[nc_idx][1] <= i:
            nc_idx += 1
        if nc_idx < len(non_code) and non_code[nc_idx][0] <= i:
            _, ne, kind = non_code[nc_idx]
            if kind == "cm":
                finish_word()
            else:
                if not first_char:
                    first_char = '"'
                last_sig = '"'
                cur_word.clear()
                last_word = ""
            i = ne
            continue

        while ct_idx < len(continuations) and continuations[ct_idx][1] <= i:
            ct_idx += 1
        if ct_idx < len(continuations) and continuations[ct_idx][0] <= i:
            finish_word()
            i = continuations[ct_idx][1]
            continue

        c = text[i]
        if c in " \t\f\v\u00a0":
            finish_word()
            i += 1
            continue

        # ${...} 는 중괄호 변수 이름이지 스크립트 블록이 아니다
        if c == "$" and i + 1 < n and text[i + 1] == "{":
            if not first_char:
                first_char = c
            end_brace = text.find("}", i + 2)
            i = n if end_brace < 0 else end_brace + 1
            last_sig = "}"
            cur_word.clear()
            last_word = ""
            continue

        # $( ... ) 와 @( ... ) 는 내부에 여러 문장(;·줄바꿈)을 가질 수 있는 하위식 블록이다
        if (c == "$" or c == "@") and i + 1 < n and text[i + 1] == "(":
            if not first_char:
                first_char = c
            if not has_assign and paren == 0 and bracket == 0:
                emit(stmt_start, i)
            block_stack.append((stmt_start, first_char, has_assign, ")", paren, bracket))
            paren = bracket = 0
            reset_stmt(i + 2)
            last_sig = "("
            i += 2
            continue

        if c == "{":
            if not first_char:
                first_char = c
            if not has_assign and paren == 0 and bracket == 0:
                emit(stmt_start, i)
            block_stack.append((stmt_start, first_char, has_assign, "}", paren, bracket))
            paren = bracket = 0
            reset_stmt(i + 1)
            last_sig = "{"
            i += 1
            continue

        if c == "}" and paren == 0 and bracket == 0 and block_stack and block_stack[-1][3] == "}":
            emit(stmt_start, i)
            outer_start, outer_first, outer_assign, _, outer_paren, outer_bracket = block_stack.pop()
            paren, bracket = outer_paren, outer_bracket
            if outer_assign or paren > 0 or bracket > 0:
                stmt_start = outer_start
                first_char = outer_first
                has_assign = outer_assign
                cur_word.clear()
                last_word = ""
            else:
                reset_stmt(i + 1)
            last_sig = "}"
            i += 1
            continue

        if c == ")" and paren == 0 and bracket == 0 and block_stack and block_stack[-1][3] == ")":
            emit(stmt_start, i)
            outer_start, outer_first, outer_assign, _, outer_paren, outer_bracket = block_stack.pop()
            paren, bracket = outer_paren, outer_bracket
            if outer_assign or paren > 0 or bracket > 0:
                stmt_start = outer_start
                first_char = outer_first
                has_assign = outer_assign
                cur_word.clear()
                last_word = ""
            else:
                reset_stmt(i + 1)
            last_sig = ")"
            i += 1
            continue

        if c == "(":
            if not first_char:
                first_char = c
            paren += 1
            last_sig = c
            cur_word.clear()
            last_word = ""
            i += 1
            continue
        if c == ")":
            if paren > 0:
                paren -= 1
            last_sig = c
            cur_word.clear()
            last_word = ""
            i += 1
            continue
        if c == "[":
            if not first_char:
                first_char = c
            bracket += 1
            last_sig = c
            cur_word.clear()
            last_word = ""
            i += 1
            continue
        if c == "]":
            if bracket > 0:
                bracket -= 1
            last_sig = c
            cur_word.clear()
            last_word = ""
            i += 1
            continue

        if paren == 0 and bracket == 0:
            if c == ";":
                emit(stmt_start, i)
                reset_stmt(i + 1)
                last_sig = c
                i += 1
                continue
            if (c == "&" and text.startswith("&&", i)) or (c == "|" and text.startswith("||", i)):
                emit(stmt_start, i)
                i += 2
                reset_stmt(i)
                last_sig = ";"
                continue
            if c == "&" and not has_assign and not (i > 0 and text[i - 1] == ">") and last_sig not in ("", ";", "|", "{", "(", "=", ",", "+"):
                emit(stmt_start, i)
                reset_stmt(i + 1)
                last_sig = ";"
                i += 1
                continue
            if c == "|" and not has_assign:
                emit(stmt_start, i)
                reset_stmt(i + 1)
                last_sig = "|"
                i += 1
                continue
            if c in "\r\n":
                finish_word()
                if last_sig in ",+=|" or last_word in _CONT_WORD_OPS:
                    i += 1
                    continue
                emit(stmt_start, i)
                reset_stmt(i + 1)
                last_sig = ""
                i += 1
                continue
            if c == "=":
                if not first_char:
                    first_char = c
                if not has_assign and first_char in "$[(":
                    has_assign = True
                last_sig = c
                cur_word.clear()
                last_word = ""
                i += 1
                continue

        if not first_char:
            first_char = c
        if c == "-" or c.isalnum():
            if not cur_word:
                last_word = ""
            cur_word.append(c)
        else:
            cur_word.clear()
            last_word = ""
        last_sig = c
        i += 1

    emit(stmt_start, n)
    while block_stack:
        outer_start, _, outer_assign, _, _, _ = block_stack.pop()
        if outer_assign:
            emit(outer_start, n)
    return spans


def _ticks_in_range(ticks, start, end):
    lo = bisect_left(ticks, start)
    hi = bisect_left(ticks, end)
    return ticks[lo:hi]


def _build_var_flow_index(scanned, ticks, non_code, nc_starts, continuations, cont_starts):
    """문장 간 변수 연결 성분을 한 번의 선형 통과로 미리 계산한다.
    반환: (var_to_comp, comp_ticks, comp_special, has_dynamic_var)."""
    has_dyn = _has_code_match(_DYNAMIC_VAR_CONSTRUCT, scanned, non_code, nc_starts)
    spans = _statement_spans(scanned, non_code, nc_starts, continuations, cont_starts)
    stmts = []
    var_to_stmts = {}
    for idx, (s, e) in enumerate(spans):
        svars = _extract_vars(scanned, s, e, non_code, nc_starts)
        if not svars:
            continue
        sticks = _ticks_in_range(ticks, s, e)
        stmts.append((s, e, svars, sticks))
        s_idx = len(stmts) - 1
        for v in svars:
            var_to_stmts.setdefault(v, []).append(s_idx)

    var_to_comp = {}
    comp_ticks = []
    comp_special = []
    visited_stmts = set()
    for start_var in var_to_stmts:
        if start_var in var_to_comp:
            continue
        cid = len(comp_ticks)
        cticks = set()
        cspec = False
        queue = [start_var]
        var_to_comp[start_var] = cid
        while queue:
            v = queue.pop()
            if v in _SPECIAL_FLOW_VARS:
                cspec = True
            for s_idx in var_to_stmts.get(v, ()):
                if s_idx in visited_stmts:
                    continue
                visited_stmts.add(s_idx)
                _, _, svars, sticks = stmts[s_idx]
                if sticks:
                    cticks.update(sticks)
                for nv in svars:
                    if nv not in var_to_comp:
                        var_to_comp[nv] = cid
                        queue.append(nv)
        comp_ticks.append(sorted(cticks))
        comp_special.append(cspec)
    return var_to_comp, comp_ticks, comp_special, has_dyn


def _inside_any_span(spans, starts, pos):
    idx = bisect_right(starts, pos) - 1
    return idx >= 0 and pos < spans[idx][1]


def find_problem(command):
    """막아야 하면 Problem(게시 명령 일치, 백틱 위치 목록, 끝까지 못 읽음, 간접 실행에서 찾음)을, 아니면 None."""
    if BT not in command:
        return None
    raw_matches = list(PUBLISH.finditer(command))
    if not raw_matches:
        return None

    scanned = command[:MAX_LEN]
    try:
        ticks, indirect_extra, has_indirect_eval, meta = _find_ticks_with_meta(scanned)
    except Exception:   # "$( 를 아주 깊게 겹친 RecursionError 등: 끝까지 못 읽은 게시 명령은 막는다
        m = next((x for x in raw_matches if _carries_text(command, x)), None)
        return Problem(m, [], True, False) if m else None

    non_code = meta.non_code
    nc_starts = [s for s, _, _ in non_code]
    continuations = meta.continuations
    cont_starts = [s for s, _ in continuations]

    has_indirect_call = (
        not has_indirect_eval
        and _has_code_match(_INDIRECT_CALL, scanned, non_code, nc_starts)
    )
    force_whole = has_indirect_eval or has_indirect_call or meta.unterminated

    # 간접 실행·미닫힘이 있으면 기존처럼 모든 게시 일치(문자열 안 포함)를 대상으로 삼고 명령 전체를 검사한다.
    if force_whole:
        m = next((x for x in raw_matches if _carries_text(command, x)), None)
        if not m:
            return None
        if ticks:
            return Problem(m, ticks, False, indirect_extra)
        if len(command) > MAX_LEN:
            return Problem(m, [], True, False)
        return None

    # 코드 자리에 있는 활성 게시 명령만 골라 문장 단위로 검사한다.
    closers = _build_match_closers(scanned, non_code, continuations)
    first_active = None
    flow_index = None   # (var_to_comp, comp_ticks, comp_special, has_dyn) — 변수 참조 시 1회 구축
    active_scopes = []  # (stmt_end, nested_spans, nested_starts) — 같은 문장 평면 인자 중복 스캔 방지

    for m in raw_matches:
        if m.start() >= MAX_LEN:
            if _carries_text(command, m):
                return Problem(m, [], True, False)
            continue
        if _enclosed_in_non_code(non_code, nc_starts, m.start(), min(m.end(), MAX_LEN)):
            continue
        while active_scopes and active_scopes[-1][0] <= m.start():
            active_scopes.pop()
        if active_scopes and not _inside_any_span(active_scopes[-1][1], active_scopes[-1][2], m.start()):
            continue

        stmt_end, tokens, nested_spans, ambiguous = _publish_stmt_end_and_tokens(
            scanned, m.end(), non_code, nc_starts, continuations, cont_starts, closers
        )
        if stmt_end > m.end():
            active_scopes.append((stmt_end, nested_spans, [ns for ns, _ in nested_spans]))

        piped_in = _is_piped_in(scanned, m.start(), non_code, nc_starts, continuations, cont_starts)
        carries, needs_whole = _classify_publish(m, tokens, piped_in)
        if not carries:
            continue
        if first_active is None:
            first_active = m
        if not ticks:
            continue
        if ambiguous or needs_whole:
            return Problem(m, ticks, False, indirect_extra)

        # 인라인 전용 게시 명령: 1) 게시 문장 자체의 실행되는 백틱
        direct_ticks = _ticks_in_range(ticks, m.start(), stmt_end)
        if direct_ticks:
            return Problem(m, direct_ticks, False, False)

        # 2) 게시 문장이 참조하는 변수·하위식의 연결 성분 조회 (O(|ref_vars|))
        ref_vars = _extract_vars(scanned, m.end(), stmt_end, non_code, nc_starts)
        if not ref_vars:
            continue
        if ref_vars & _SPECIAL_FLOW_VARS:
            return Problem(m, ticks, False, False)

        if flow_index is None:
            flow_index = _build_var_flow_index(scanned, ticks, non_code, nc_starts, continuations, cont_starts)
        var_to_comp, comp_ticks, comp_special, has_dyn = flow_index
        if has_dyn:
            return Problem(m, ticks, False, False)

        flow_ticks = set()
        seen_comps = set()
        for v in ref_vars:
            cid = var_to_comp.get(v)
            if cid is None or cid in seen_comps:
                continue
            seen_comps.add(cid)
            if comp_special[cid]:
                return Problem(m, ticks, False, False)
            if comp_ticks[cid]:
                flow_ticks.update(comp_ticks[cid])
        if flow_ticks:
            return Problem(m, sorted(flow_ticks), False, False)

    if first_active is not None and len(command) > MAX_LEN:
        return Problem(first_active, [], True, False)
    return None


def _line_col(text, pos):
    """줄:칸. 줄바꿈은 CRLF·LF·CR 어느 것이든 하나로 센다."""
    breaks = list(re.finditer(r"\r\n|\r|\n", text[:pos]))
    line = len(breaks) + 1
    col = pos - (breaks[-1].end() if breaks else 0) + 1
    return line, col


def format_message(command, problem):
    shown = " ".join(_CONTINUATION.sub(" ", problem.match.group(0)).split())
    if len(shown) > 200:   # 긴 옵션 목록이 안내문을 입력만큼 키우지 않게 한다
        shown = shown[:100] + " ... " + shown[-60:]
    if problem.incomplete:
        lines = [
            "[backtick-check-hook] [ps-publish-guard] Blocked an incomplete PowerShell publishing scan.\n"
            "  막음: 이 PowerShell 명령은 gh·git으로 글을 게시하는데, 너무 깊게 중첩됐거나"
            " 너무 길거나 특이해서 끝까지 검사하지 못했다.",
            "  게시 명령: %s" % shown,
        ]
    else:
        ticks = problem.ticks
        where = ", ".join("%d:%d" % _line_col(command, p) for p in ticks[:5])
        more = "" if len(ticks) <= 5 else " (외 %d곳)" % (len(ticks) - 5)
        lines = [
            "[backtick-check-hook] [ps-publish-guard] Blocked an active backtick in a PowerShell publishing command.\n"
            "  막음: 이 PowerShell 명령은 gh·git으로 글을 게시하는데, 작은따옴표 밖에 백틱이 있다.",
            "  게시 명령: %s" % shown,
            "  백틱 위치(줄:칸): %s%s" % (where, more),
        ]
        if problem.indirect:
            lines.append("  Invoke-Expression·iex·powershell -c·[scriptblock]::Create가 있어 작은따옴표 안의 글도"
                         " 코드로 읽었다. 그 글이 실행될 때 안쪽 큰따옴표의 백틱은 이스케이프가 된다.")
    lines += [
        "  Write the body directly with a file-writing tool and pass its path to gh or git.",
        "  PowerShell 큰따옴표와 @\"...\"@ 안에서 백틱은 이스케이프 문자다: `a는 벨 문자, `r은 줄 되돌림이 되고,",
        "  다른 글자 앞의 백틱은 사라질 수 있다.",
        "  Windows PowerShell 5.1은 네이티브 프로그램(gh·git)에 인자를 넘길 때 인자 안의 큰따옴표를 지운다.",
        "  이 경우 권장하는 본문 전달 방법은 파일뿐이다. 파일 쓰기 도구로 본문을 파일에 직접 쓰고",
        "  gh release create|edit --notes-file, gh pr|issue ... --body-file, git commit -F, git tag -F로 넘긴다",
        "  (gh api는 -F body=@파일, git merge·notes도 -F. close·reopen의 -c는 파일을 못 받으니 comment --body-file로).",
        "  백틱이 게시와 상관없는 줄(예: 다른 문자열의 `n)에 있으면 게시 명령을 따로 실행한다.",
    ]
    return "\n".join(lines) + "\n"


def _block_code(argv):
    for arg in argv:
        if arg.startswith("--block-code="):
            try:
                code = int(arg.split("=", 1)[1])
            except ValueError:
                continue
            if 1 <= code <= 255:
                return code
    return 2


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", "replace")
        if "--raw" in argv:
            command = raw
        else:
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("tool_name") not in TOOL_NAMES:
                return 0
            tool_input = data.get("tool_input")
            command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str) or not command:
            return 0
        problem = find_problem(command)
        if not problem:
            return 0
        message = format_message(command, problem)
    except Exception:   # 검사기 고장이 작업을 막지 않게 한다
        return 0
    try:
        sys.stderr.buffer.write(message.encode("utf-8", "backslashreplace"))
        sys.stderr.flush()
    except Exception:
        try:
            sys.stderr.buffer.write(b"[backtick-check-hook] [ps-publish-guard] BLOCKED: a PowerShell command that publishes text with gh or "
                                    b"git has a backtick outside single quotes, or could not be checked to the end. "
                                    b"Only files are safe on Windows PowerShell 5.1: write the text to a file and pass "
                                    b"it with --notes-file / --body-file / -F.\n")
            sys.stderr.flush()
        except Exception:
            pass
    return _block_code(argv)


if __name__ == "__main__":
    sys.exit(main())
