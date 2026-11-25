#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ps_publish_guard.py - PowerShell 명령 실행 전 검사 훅 (Claude Code PreToolUse, matcher "PowerShell").

PowerShell interprets backticks in expandable strings and here-strings as escapes.
Write publishing text with a file-writing tool and pass its path to gh or git.

막는 것:
  gh로 글을 게시하는 명령(release create/new/edit, pr create/new/edit/comment/review/merge/close/reopen,
  issue create/new/edit/comment/close/reopen, api)이나 git으로 메시지를 쓰는 명령(commit, tag, notes,
  merge)이 든 PowerShell 명령에서, 작은따옴표 문자열·@'...'@ 히어스트링·주석·줄 이음 밖에 백틱이 있으면
  막는다. 큰따옴표 문자열, @"..."@ 히어스트링, 따옴표 없는 인자 안의 백틱이 여기에 든다.
  git commit과 gh release·pr·issue는 늘 글을 넘긴다고 본다(-F 파일·-F - 도 그렇다: 같은 명령에서 큰따옴표로
  그 파일이나 파이프를 채웠을 수 있다). git tag는 주석 태그를 만드는 꼴(-a -s -m -F -u, 묶음 포함), git notes는
  add·append·edit·copy, git merge는 -m·-F, gh api는 -f·-F 필드(붙여 쓴 -fbody=도)나 --input이 있을 때만 게시로
  본다. 읽기만 하는 명령(git tag -l, git notes show, gh api ... --jq)은 다른 자리의 백틱 때문에 막지 않는다.
  merge-base처럼 하이픈으로 이어진 낱말은 하위 명령으로 보지 않는다. gh의 -R·--repo는 gh 바로 뒤나 묶음 낱말
  뒤에 와도, 값을 붙여 써도(-Ro/r) 읽는다. git 옵션은 하위 명령 앞 32개까지만 읽는다.
  게시 명령은 이런 꼴로 써도 알아본다: 하위 명령 낱말을 따옴표로 감싼 꼴("release" "create"), gh·git과
  옵션·하위 명령 낱말 사이의 줄 이음(줄 끝 백틱. LF·CRLF·CR), 값을 따로 받는 git 옵션(-c, -C, --git-dir,
  --work-tree, --namespace, --config-env, --attr-source. 값은 "..."·'...'·따옴표 없는 꼴 모두).
  Invoke-Expression·iex, 또는 powershell·pwsh(.exe)의 -c·-Command가 든 명령은 작은따옴표 문자열과
  @'...'@ 본문도 코드로 한 번 더 읽는다(''는 '로 풀고, 찾은 자리는 원문의 줄:칸으로 돌려 적는다). 그 글이
  코드로 실행될 때 안쪽 큰따옴표의 백틱이 이스케이프가 되기 때문이다.
  게시 명령인데 끝까지 읽지 못하면 막는다: "$( 를 아주 깊게 겹쳐 RecursionError가 날 때, 읽다가 다른
  예외가 날 때, MAX_LEN보다 길고 앞부분에서 백틱을 못 찾았을 때.
  게시할 글은 파일 쓰기 도구로 파일에 쓰고 --notes-file·--body-file·-F 파일로 넘긴다.
  Windows PowerShell 5.1은 네이티브 프로그램에 넘기는 인자 안의 큰따옴표를 지우므로, 작은따옴표로 감싸
  넘기는 것도 안전하지 않다.
허용하는 것: 작은따옴표와 @'...'@ 안의 백틱(간접 실행이 없으면 글자 그대로다), 주석(# 한 줄,
  <# ... #>), 줄 끝의 백틱(다음 줄로 잇기), 그리고 gh·git으로 글을 쓰지 않는 명령의 백틱("`n" 같은
  정상 이스케이프). 명령 하나가 gh 게시와 다른 일을 함께 하면, 다른 일의 백틱 때문에 막힐 수 있다
  (명령을 나눈다).

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
  파일 안의 명령, Bash 도구에서 띄운 PowerShell(powershell -c '...'), 스플래팅(gh @args), Start-Process,
  & $var처럼 명령 이름이나 인자를 변수에 담아 넘기는 꼴, -EncodedCommand·[scriptblock]::Create처럼 다른
  간접 실행, 위 목록 밖의 gh·git 글쓰기(gh repo edit --description, gh secret set --body, git stash -m 등),
  그리고 해당 훅이 호출되지 않는 실행 경로.
  PowerShell 파서와 동작이 다른 드문 꼴도 있다: 식 바로 뒤에 붙은 주석에
  작은따옴표가 든 꼴($v = $base# it's)은 그 뒤 줄을 문자열로 잘못 읽어 놓친다. -Command 없이 넘긴
  powershell '...'(5.1은 -Command가 기본값), 줄을 넘겨 쓴 -Command, 3단보다 깊은 iex, gh <# … #> release
  처럼 사이에 주석을 둔 꼴, git -C (식)처럼 괄호 값을 둔 꼴, git commit-tree 같은 배관 명령도 보지 못한다.
  반대로 주석이나 문자열 안의 'git commit' 같은 낱말, 같은 명령 어딘가의 iex, git commit -F 파일과 함께 쓴
  관계없는 이스케이프("`n") 때문에 막힐 수 있다(게시 명령을 따로 실행하면 된다).
  파이썬 3.11 미만에서는 소유 한정자(++, *+) 대신 보통 한정자를 쓴다. 판정은 같지만 백틱+CRLF 줄 이음이 아주
  많은 명령에서는 느려질 수 있다.

동작: bash_quote_guard.py와 같다. 표준 입력으로 훅 JSON을 받는다. 막을 때는 표준 오류에 이유를 쓰고
  --block-code로 준 코드(기본 2)로 끝난다. 그 밖의 모든 경우와 이 스크립트 자신의 오류는 0이다
  (검사기 고장이 작업을 막지 않게 한다). 예외는 하나다: 게시 명령을 끝까지 읽지 못하면 위처럼 막는다.
  훅 명령은 42를 받아 그때만 2로 바꾼다.
  손으로 확인: python ps_publish_guard.py --raw < 명령.txt
"""
from __future__ import annotations

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

# 글을 코드로 실행하는 명령. 이것이 있으면 작은따옴표 안도 코드로 읽는다.
INDIRECT = re.compile(
    r"(?i)(?<![\w.$-])(?:invoke-expression|iex)(?![\w.-])"
    r"|(?<![\w.$-])(?:powershell|pwsh)(?:\.exe)?" + _Q + r"?[^\r\n;|]{0,300}?\s[-/]{1,2}"
    r"c(?:o(?:m(?:m(?:a(?:n(?:d(?:withargs)?)?)?)?)?)?|wa)?(?![\w-])"
)

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


def _scan_dq(text, i, out, sq):
    """큰따옴표 문자열 안(i는 여는 따옴표 다음)을 읽는다. 백틱을 모으고 닫는 따옴표 다음 위치를 돌려준다.
    $( ... ) 안은 코드라 그 안의 문자열도 같은 규칙으로 본다."""
    n = len(text)
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
            return i + 1
        if c == "$" and text.startswith("$(", i):
            i = _scan_code(text, i + 2, out, sq, stop_at_paren=True)
            continue
        i += 1
    return n


def _scan_code(text, i, out, sq, stop_at_paren=False):
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
                i = n if m is None else m.start()
                continue
            i += 1                             # 낱말 안의 #은 글자다(a#b, title=#42)
            continue
        if c == "<" and state != WORD and text.startswith("<#", i):
            end = text.find("#>", i + 2)
            i = n if end < 0 else end + 2
            state = START
            continue
        if c == "@" and state != WORD and i + 1 < n and (text[i + 1] in DQ or text[i + 1] in SQ):
            body = _here_body(text, i)
            if body >= 0:
                double = text[i + 1] in DQ
                body_end, after = _here_end(text, body, double)
                if double:
                    k = text.find(BT, body, body_end)
                    while k >= 0:
                        out.append(k)
                        k = text.find(BT, k + 1, body_end)
                else:
                    sq.append((body, body_end, False))
                i = after
                state = START                  # 닫는 표지 바로 뒤의 #은 주석이다
                cmd_pos = False
                continue
        if c in SQ:                            # 낱말 안의 문자열이면 낱말이 이어지고, 토큰 첫머리면 문자열이
            body_end, after = _sq_end(text, i)  # 토큰이라 닫는 따옴표 뒤가 다시 첫머리다. 둘 다 state 그대로
            sq.append((i + 1, body_end, True))
            i = after
            cmd_pos = False
            continue
        if c in DQ:
            i = _scan_dq(text, i + 1, out, sq)
            cmd_pos = False
            continue
        if c == BT:
            if text.startswith("\n", i + 1) or text.startswith("\r", i + 1):
                i += 3 if text.startswith("\r\n", i + 1) else 2   # 줄 이음
                state = START
                continue
            out.append(i)
            i += 2
            if state == START:
                state = WORD
            cmd_pos = False
            continue
        if c == "$" and text.startswith("$(", i):
            i = _scan_code(text, i + 2, out, sq, stop_at_paren=True)
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


def _find_ticks(text):
    """(백틱 위치 목록, 간접 실행 때문에 새로 찾은 것이 있는지). 위치는 원문 기준으로 정렬한다."""
    out, sq = [], []
    _scan_code(text, 0, out, sq)
    found = set(out)
    indirect = False
    if sq and INDIRECT.search(text):
        extra = set(_code_in_sq(text, sq, None, 1)) - found
        indirect = bool(extra)
        found |= extra
    return sorted(found), indirect


CARRY_WINDOW = 4000  # 게시 명령 뒤에서 글을 넘기는 플래그를 찾는 범위(글자). 일치마다 끝까지 읽으면 시간이 제곱으로 는다
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
    """게시 명령이 글을 넘기는가. git commit과 gh release·pr·issue는 늘 그렇다고 본다(-F 파일이나 -F - 도:
    같은 명령에서 큰따옴표로 그 파일이나 파이프를 채웠을 수 있다). git tag·notes·merge와 gh api는 위의 꼴일
    때만 그렇다고 보고, 읽기만 하는 명령(git tag -l, git notes show, gh api ... --jq)은 다른 자리의 백틱 때문에
    막지 않는다."""
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


def find_problem(command):
    """막아야 하면 Problem(게시 명령 일치, 백틱 위치 목록, 끝까지 못 읽음, 간접 실행에서 찾음)을, 아니면 None."""
    if BT not in command:
        return None
    m = next((x for x in PUBLISH.finditer(command) if _carries_text(command, x)), None)
    if not m:
        return None
    try:
        ticks, indirect = _find_ticks(command[:MAX_LEN])
    except Exception:   # "$( 를 아주 깊게 겹친 RecursionError 등: 끝까지 못 읽은 게시 명령은 막는다
        return Problem(m, [], True, False)
    if ticks:
        return Problem(m, ticks, False, indirect)
    if len(command) > MAX_LEN:
        return Problem(m, [], True, False)
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
            lines.append("  Invoke-Expression·iex·powershell -c가 있어 작은따옴표 안의 글도 코드로 읽었다."
                         " 그 글이 실행될 때 안쪽 큰따옴표의 백틱은 이스케이프가 된다.")
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
