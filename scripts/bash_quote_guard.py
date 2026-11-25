#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check Bash commands for backticks subject to command substitution.

Read a hook event from stdin or pass --raw for a command string. The default
policy checks backticks. --strict also checks dollar-parenthesis substitution
mixed into text. The scanner checks both the supplied command and a variant
with folded backslashes. On Windows it models Git Bash carriage-return handling.
A bounded recursive scan reports the violations found within its budget.

--self-test runs the installed plugin's declared Bash and Monitor hooks against
synthetic inputs. The test inputs are sent to the hook, never to a command shell
for evaluation. Success is exit 10; diagnostics are printed on failure.
"""
from __future__ import annotations

import bisect
import json
import sys
import time
from collections import namedtuple

RULE_BACKTICK = "backtick"
RULE_DOLLAR_PAREN = "dollar-paren-in-text"
AS_WRITTEN = "as-written"
FOLDED = "backslash-folded"
MAX_DEPTH = 150            # 중첩이 이보다 깊으면 거기서 읽기를 그만둔다
TIME_BUDGET = 3.0          # 읽는 데 쓰는 시간(초). 넘기면 거기서 그만둔다
TOOL_NAMES = ("Bash", "Monitor")   # 이 도구들의 tool_input.command를 본다
GUARD_FILE = "bash_quote_guard.py"
SELF_TEST_OK = 10          # 자가 점검이 정상일 때의 종료 코드. 0은 "점검이 돌지 않았다"로 읽는다
SELF_TEST_FAILED = 3
STRIP_CR = sys.platform == "win32"
_HEREDOC_END = " \t\n;|&<>()"
_WORD_END = " \t\n;|&()<>"
_PARAM_OPS = "#%^,~:-=?+/"
_COMMAND_STARTERS = ("then", "do", "else", "elif", "!", "time", "if", "while", "until", "{")

Violation = namedtuple("Violation", "rule index line col where variant near")


class _GiveUp(Exception):
    """너무 깊거나 시간이 다 됐다. 여기서 읽기를 그만둔다."""


def fold_backslashes(command: str) -> str:
    """일부 Windows 실행 경로에서 관찰한 역슬래시 접힘을 적용한다: 연속한 역슬래시 k개 -> 올림(k/2)개.
    큰따옴표 바로 앞의 역슬래시는 그대로다(실행 경로가 그 자리만 미리 두 배로 늘려 넘긴다)."""
    if "\\\\" not in command:
        return command
    out = []
    i, n = 0, len(command)
    while i < n:
        j = command.find("\\", i)
        if j < 0:
            out.append(command[i:])
            break
        out.append(command[i:j])
        k = j
        while k < n and command[k] == "\\":
            k += 1
        run = k - j
        if k < n and command[k] == '"':
            out.append("\\" * run)
        else:
            out.append("\\" * ((run + 1) // 2))
        i = k
    return "".join(out)


def _drop_continuations(text: str):
    """역슬래시-줄바꿈을 뺀다. 줄 끝의 역슬래시가 홀수 개일 때만 줄 잇기다.
    (뺀 글, 뺀 자리 목록)을 돌려준다. 자리는 뺀 글에서의 위치이고, 그 자리마다 두 글자가 빠졌다."""
    if "\\\n" not in text:
        return text, []
    out, cuts = [], []
    i = length = 0
    while True:
        j = text.find("\\\n", i)
        if j < 0:
            out.append(text[i:])
            break
        k = j
        while k > i and text[k - 1] == "\\":
            k -= 1
        if (j - k + 1) % 2 == 1:
            out.append(text[i:j])
            length += j - i
            cuts.append(length)
        else:
            out.append(text[i:j + 2])
            length += j + 2 - i
        i = j + 2
    return "".join(out), cuts


def as_bash_reads(text: str) -> str:
    """Git Bash는 읽는 글에서 CR 문자를 모두 버린다(따옴표 안에서도). Windows에서는 똑같이 뺀다."""
    return text.replace("\r", "") if STRIP_CR else text


class _Scanner:
    """Bash가 읽는 순서대로 따옴표 상태를 따라가며 '실행되는 명령 치환'을 찾는다."""

    def __init__(self, text: str, pid_paren_nests: bool = False, deadline=None, depth: int = 0):
        self.s = text
        self.n = len(text)
        self.i = 0
        self.depth = depth
        self.deadline = deadline
        self.gave_up = False
        self.found: list = []     # 위반: (규칙, 위치, 자리 설명)
        self.active: list = []    # Bash가 실행하는 모든 명령 치환: (종류, 위치). 허용되는 것도 포함
        self.pending: list = []   # 본문을 기다리는 히어독: (구분자, 탭 제거, 따옴표 여부)
        self.not_arith: set = set()   # "$((" 나 "((" 로 시작하지만 산술이 아니라고 이미 판정한 자리
        self.comsub_depth = 0     # 지금 자리를 감싼 $( 와 <( 의 수(히어독을 "구분자)" 로 끝내는 옛 규칙에 쓴다)
        # "$$(" 를 읽는 두 방식. Bash는 "$$"를 프로세스 번호로 바꾸고 괄호는 글자로 두지만(거짓),
        # 따옴표와 괄호의 짝을 맞출 때는 둘째 달러와 괄호를 치환처럼 읽는다(참). 두 방식을 모두 돌려 합친다.
        self.pid_paren_nests = pid_paren_nests

    # ---- 공통 -------------------------------------------------------------
    def _flag(self, rule: str, index: int, where: str) -> None:
        self.found.append((rule, index, where))

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise _GiveUp("depth")
        if self.deadline is not None and time.perf_counter() > self.deadline:
            raise _GiveUp("time")

    def _leave(self) -> None:
        self.depth -= 1

    def _snapshot(self, subs):
        return (len(self.found), len(self.active), len(subs) if subs is not None else 0, list(self.pending))

    def _restore(self, state, subs) -> None:
        del self.found[state[0]:]
        del self.active[state[1]:]
        if subs is not None:
            del subs[state[2]:]
        self.pending = state[3]

    # ---- 따옴표와 글 -------------------------------------------------------
    def _single(self) -> None:
        """i는 여는 작은따옴표. 닫는 작은따옴표 다음으로 옮긴다(안에서는 아무것도 확장되지 않는다)."""
        j = self.s.find("'", self.i + 1)
        self.i = self.n if j < 0 else j + 1

    def _single_as_text(self, where: str) -> None:
        """i는 여는 작은따옴표. 짝은 맞추되 안쪽을 확장되는 글로 읽는다
        (산술식, 첨자, 큰따옴표 안 ${v:-'...'}: 여기서 작은따옴표는 글자일 뿐이다)."""
        j = self.s.find("'", self.i + 1)
        end = self.n if j < 0 else j
        self._text_span(self.i + 1, end, where)
        self.i = self.n if j < 0 else j + 1

    def _ansi(self) -> None:
        """i는 $'...'의 달러 기호. 역슬래시 이스케이프를 따라 닫는 작은따옴표 다음으로 옮긴다."""
        s, n = self.s, self.n
        i = self.i + 2
        while i < n:
            c = s[i]
            if c == "\\":
                i += 2
            elif c == "'":
                i += 1
                break
            else:
                i += 1
        self.i = min(i, n)

    def _backtick(self, where: str) -> None:
        """i는 여는 백틱. 규칙 A로 적고 닫는 백틱 다음으로 옮긴다.
        Bash는 따옴표와 상관없이 이스케이프 안 된 다음 백틱을 짝으로 본다. 짝이 없으면 끝까지다."""
        self._flag(RULE_BACKTICK, self.i, where)
        self.active.append(("backtick", self.i))
        s, n = self.s, self.n
        j = self.i + 1
        while j < n and s[j] != "`":
            j += 2 if s[j] == "\\" else 1
        self.i = min(j + 1, n)

    def _text(self, where: str) -> None:
        """확장되는 글을 끝까지 읽는다(따옴표 없는 히어독 본문, 산술식·첨자 안 작은따옴표의 안쪽).
        여기서는 따옴표가 글자일 뿐이다. 백틱과 "$("는 실행된다."""
        self._enter()
        s, n = self.s, self.n
        subs: list = []
        while self.i < n:
            c = s[self.i]
            if c == "\\":
                self.i += 2
            elif c == "`":
                self._backtick(where)
            elif c == "$":
                self._dollar(subs, in_dq=True)
            else:
                self.i += 1
        for a in subs:
            self._flag(RULE_DOLLAR_PAREN, a, where)
        self._leave()

    def _text_span(self, a: int, b: int, where: str) -> None:
        """s[a:b]를 확장되는 글로 따로 읽어 결과를 합친다(안쪽 읽기가 b를 넘어가지 못하게 한다)."""
        if b > a:
            self._text_string(self.s[a:b], a, where)

    def _text_string(self, text: str, base: int, where: str, cuts=()) -> None:
        """글 하나를 확장되는 글로 따로 읽어 결과를 합친다. 위치는 base를 더해 적는다.
        cuts는 이 글에서 두 글자(역슬래시-줄바꿈)가 빠진 자리들이다: 원문 위치로 되돌리는 데 쓴다."""
        if not text:
            return
        sub = _Scanner(text, self.pid_paren_nests, self.deadline, self.depth)
        try:
            sub._text(where)
        finally:
            self.found += [(rule, base + index + 2 * bisect.bisect_right(cuts, index), place)
                           for rule, index, place in sub.found]
            self.active += [(kind, base + index + 2 * bisect.bisect_right(cuts, index)) for kind, index in sub.active]

    def _double(self) -> None:
        """i는 여는 큰따옴표. 안의 백틱은 A, 글과 섞인 "$("는 B로 적는다."""
        self._enter()
        s, n = self.s, self.n
        self.i += 1
        start = self.i
        subs: list = []      # 이 문자열에 속한 "$("의 위치(${...}·$((...)) 안쪽 포함)
        pieces = 0           # 맨 위 층에 있는 달러 확장의 개수
        first = (-1, -1)
        end = -1
        while self.i < n:
            c = s[self.i]
            if c == "\\":
                nxt = s[self.i + 1] if self.i + 1 < n else ""
                self.i += 2 if (nxt and nxt in "$`\"\\\n") else 1
            elif c == '"':
                end = self.i
                self.i += 1
                break
            elif c == "`":
                self._backtick("double-quoted text")
            elif c == "$":
                a = self.i
                self._dollar(subs, in_dq=True)
                if pieces == 0:
                    first = (a, self.i)
                pieces += 1
            else:
                self.i += 1
        whole = end >= 0 and pieces == 1 and first == (start, end)
        if subs and not whole:
            for a in subs:
                self._flag(RULE_DOLLAR_PAREN, a, "double-quoted text")
        self._leave()

    def _comsub(self) -> None:
        """i는 "$(" 나 "<(" 다음. 닫는 ")" 다음으로 옮긴다. 히어독 대기 목록은 치환마다 따로 둔다."""
        outer, self.pending = self.pending, []
        self.comsub_depth += 1
        self._code("cmdsub")
        self.comsub_depth -= 1
        if self.pending:
            # 본문을 만나기 전에 ")"로 닫혔다(Bash도 경고하는 잘못된 꼴). Bash는 이 줄의 나머지를 바깥 문맥으로
            # 읽고 다음 줄부터를 본문으로 읽는데, 그 이음매를 여기서 정확히 따라갈 수 없다.
            # 놓치지 않는 쪽으로: 이 뒤의 이스케이프 안 된 백틱은 모두 실행되는 것으로 본다.
            self._text_span(self.i, self.n, "after an unterminated here-document")
        self.pending = outer

    def _dollar(self, subs, in_dq: bool) -> None:
        """i는 달러 기호. $(...), $((...)), $[...], ${...}, $'...', $"..."를 처리한다.
        subs가 목록이면(큰따옴표에 속한 자리) 명령 치환의 위치를 거기에 적는다."""
        s, n = self.s, self.n
        a = self.i
        nxt = s[a + 1] if a + 1 < n else ""
        if nxt == "(":
            if s.startswith("((", a + 1) and (a, in_dq) not in self.not_arith:
                state = self._snapshot(subs)
                self.i = a + 3
                if self._arith(subs, ")"):
                    return
                self._restore(state, subs)   # "$(("로 시작하지만 산술이 아니다: 명령 치환으로 다시 읽는다
                self.not_arith.add((a, in_dq))
            self.active.append(("cmdsub", a))
            if subs is not None:
                subs.append(a)
            self.i = a + 2
            self._comsub()
        elif nxt == "{":
            if a + 2 < n and s[a + 2] in " \t\n|":
                self.active.append(("funsub", a))    # Bash 5.3의 ${ 명령; }: 안쪽은 셸 코드다
                if subs is not None:
                    subs.append(a)
                self.i = a + 3
                self._code("brace")
            else:
                self.i = a + 2
                self._param(subs, in_dq)
        elif nxt == "[":
            self.i = a + 2
            self._arith(subs, "]")                   # 옛 산술 표기 $[...]
        elif nxt == "'" and not in_dq:
            self._ansi()
        elif nxt == '"' and not in_dq:
            self.i = a + 1
            self._double()
        elif nxt == "$" and self.pid_paren_nests and s.startswith("(", a + 2):
            self.i = a + 3       # "$$(": 실행되지 않으므로 active에는 적지 않고, 짝만 치환처럼 맞춘다
            self._comsub()
        elif nxt and nxt in "$!?#*@-0123456789":
            self.i = a + 2       # $$, $?, $1 같은 특수 매개변수: "$$(" 의 "(" 는 치환의 시작이 아니다
        else:
            self.i = a + 1

    def _param(self, subs, in_dq: bool) -> None:
        """i는 "${" 다음. 짝이 맞는 "}" 다음으로 옮긴다.
        작은따옴표가 하는 일은 자리에 따라 다르다. ${v#'x'}·${v//'x'/}의 무늬에서는 진짜 따옴표다.
        ${v:-'x'}에서는 큰따옴표 밖이면 진짜 따옴표, 큰따옴표 안이면 짝만 맞추는 글자다(안의 백틱은 실행된다).
        ${v:'x'}의 위치 계산과 ${m['x']}의 첨자에서는 글자로 본다(산술로 계산될 때 안의 백틱이 실행된다)."""
        self._enter()
        s, n = self.s, self.n
        state = "name"       # name -> op -> word 또는 offset, name -> pattern
        op = ""
        brackets = 0
        first = True
        while self.i < n:
            c = s[self.i]
            if state == "name":
                if brackets == 0 and not first and c in "%#/^,":
                    state = "pattern"
                elif brackets == 0 and c in _PARAM_OPS:
                    state, op = "op", c
                elif c == "[":
                    brackets += 1
                elif c == "]" and brackets:
                    brackets -= 1
            elif state == "op":
                if c in _PARAM_OPS:
                    op += c
                else:
                    state = "offset" if set(op) == {":"} else "word"
            first = False
            if c == "\\":
                self.i += 2
            elif c == "}":
                self.i += 1
                break
            elif c == "`":
                self._backtick("parameter expansion")
            elif c == '"':
                self._double()
            elif c == "'":
                if state == "offset" or (state == "name" and brackets) or (state == "word" and in_dq):
                    self._single_as_text("parameter expansion")
                else:
                    self._single()
            elif c == "$":
                self._dollar(subs, in_dq or state == "offset" or (state == "name" and brackets > 0))
            else:
                self.i += 1
        self._leave()

    def _arith(self, subs, close: str) -> bool:
        """산술식을 읽는다. close가 ")"이면 i는 "$((" 또는 "((" 다음이고, "))"로 붙어 닫힐 때만 True
        (아니면 False: 부른 쪽이 되돌려 다시 읽는다). close가 "]"이면 i는 "$[" 다음이고 짝이 맞는 "]"까지다.
        산술식은 큰따옴표 글처럼 확장된다: 작은따옴표와 $'...'는 짝만 맞추는 글자이고 안의 백틱은 실행된다."""
        self._enter()
        s, n = self.s, self.n
        open_ch = "(" if close == ")" else "["
        depth = 2 if close == ")" else 1
        ok = False
        while self.i < n:
            c = s[self.i]
            if c == "\\":
                self.i += 2
            elif c == open_ch:
                depth += 1
                self.i += 1
            elif c == close:
                depth -= 1
                self.i += 1
                if close == "]":
                    if depth == 0:
                        ok = True
                        break
                elif depth == 1:
                    if self.i < n and s[self.i] == ")":
                        self.i += 1
                        ok = True
                    break
            elif c == "`":
                self._backtick("arithmetic expansion")
            elif c == '"':
                self._double()
            elif c == "'":
                self._single_as_text("arithmetic expansion")
            elif c == "$":
                self._dollar(subs, True)
            else:
                self.i += 1
        self._leave()
        return ok

    # ---- 히어독 -----------------------------------------------------------
    def _heredoc_word(self, j: int):
        """j는 구분자 낱말의 시작. (구분자, 따옴표 여부, 낱말 끝 위치)를 돌려준다."""
        s, n = self.s, self.n
        out: list = []
        quoted = False
        while j < n:
            c = s[j]
            if c in _HEREDOC_END:
                break
            if c == "\\" and j + 1 < n and s[j + 1] == "\n":
                j += 2                     # 줄 잇기는 구분자에 들어가지 않는다
                continue
            if c == "$" and j + 1 < n and s[j + 1] in "'\"":
                j += 1                     # <<$'EOF', <<$"EOF": 달러는 구분자에 들어가지 않는다
                continue
            if c == "\\":
                quoted = True
                if j + 1 < n:
                    out.append(s[j + 1])
                j += 2
            elif c == "'":
                quoted = True
                k = s.find("'", j + 1)
                if k < 0:
                    out.append(s[j + 1:])
                    j = n
                else:
                    out.append(s[j + 1:k])
                    j = k + 1
            elif c == '"':
                quoted = True
                k = j + 1
                while k < n and s[k] != '"':
                    if s[k] == "\\" and k + 1 < n:
                        k += 1
                    out.append(s[k])
                    k += 1
                j = k + 1
            else:
                out.append(c)
                j += 1
        return "".join(out), quoted, min(j, n)

    def _heredoc_bodies(self) -> None:
        """기다리던 히어독 본문을 i부터 차례로 읽고, 다시 셸 코드가 시작되는 자리로 옮긴다."""
        s, n = self.s, self.n
        waiting, self.pending = self.pending, []
        for delim, strip_tabs, quoted in waiting:
            body_start = pos = self.i
            body_end = resume = n
            while pos < n:
                line_start = pos
                pieces = []                # (원문 위치, 글): 역슬래시-줄바꿈으로 이어진 조각들
                while True:                # 따옴표 없는 히어독에서 역슬래시-줄바꿈은 다음 줄과 한 줄이다
                    eol = s.find("\n", pos)
                    piece, start = s[pos:n if eol < 0 else eol], pos
                    pos = n if eol < 0 else eol + 1
                    if not quoted and eol >= 0 and (len(piece) - len(piece.rstrip("\\"))) % 2 == 1:
                        pieces.append((start, piece[:-1]))
                        continue
                    pieces.append((start, piece))
                    break
                line = "".join(text for _start, text in pieces)
                probe = line.lstrip("\t") if strip_tabs else line
                if probe == delim:
                    body_end, resume = line_start, pos
                    break
                if self.comsub_depth and delim and probe.startswith(delim) and ")" in probe[len(delim):]:
                    # $( 나 <( 안에서는 "구분자"로 시작하고 뒤에 ")"가 있는 줄도 히어독을 끝낸다(Bash의 옛 규칙).
                    # 구분자 바로 뒤부터 다시 셸 코드다.
                    body_end = line_start
                    offset = (len(line) - len(probe)) + len(delim)
                    for start, text in pieces:
                        if offset <= len(text):
                            resume = start + offset
                            break
                        offset -= len(text)
                    break
            if not quoted:
                # Bash는 본문을 읽으면서 역슬래시-줄바꿈을 먼저 뺀다. 그 글을 확장한다.
                body, cuts = _drop_continuations(s[body_start:body_end])
                self._text_string(body, body_start, "unquoted here-document", cuts)
            self.i = resume

    # ---- 셸 코드 ----------------------------------------------------------
    def _code(self, mode: str) -> None:
        """따옴표 밖의 셸 코드를 읽는다. mode: top(끝까지), cmdsub·paren(")"에서 끝), brace("}" 낱말에서 끝)."""
        self._enter()
        s, n = self.s, self.n
        case_depth = 0       # 열려 있는 case ... esac의 수
        await_in = 0         # case를 읽었고 in을 기다리는 수
        cond = False         # [[ ... ]] 안인가: 그 안의 ( ) | < > 는 낱말의 일부다
        cond_parens = 0      # [[ ... ]] 안에서 열려 있는 괄호의 수
        ws = True            # 지금 자리가 낱말이 시작되는 자리인가(주석 판정)
        cmd = True           # 다음 낱말이 명령 자리인가(예약어 case·esac·[[ 판정)
        while self.i < n:
            c = s[self.i]
            if c == "\\":
                if self.i + 1 < n and s[self.i + 1] == "\n":
                    self.i += 2          # 줄 잇기: 낱말 상태는 그대로
                    continue
                self.i += 2
                ws = cmd = False
                continue
            if c == "\n":
                self.i += 1
                ws = cmd = True
                if self.pending:
                    self._heredoc_bodies()
                continue
            if c == " " or c == "\t":
                self.i += 1
                ws = cond_parens == 0        # [[ x =~ (a #) ]]: 괄호 안의 빈칸은 낱말의 일부다
                continue
            if c == "'":
                self._single()
                ws = cmd = False
                continue
            if c == '"':
                self._double()
                ws = cmd = False
                continue
            if c == "`":
                self._backtick("unquoted shell code")
                ws = cmd = False
                continue
            if c == "$":
                self._dollar(None, in_dq=False)
                ws = cmd = False
                continue
            if c == "#" and ws:
                eol = s.find("\n", self.i)
                self.i = n if eol < 0 else eol
                continue
            if cond:
                if ws and s.startswith("]]", self.i) and (self.i + 2 >= n or s[self.i + 2] in _WORD_END):
                    cond = False
                    cond_parens = 0
                    self.i += 2
                else:
                    if c == "(":
                        cond_parens += 1
                    elif c == ")" and cond_parens:
                        cond_parens -= 1
                    self.i += 1
                ws = cmd = False
                continue
            if c == "(":
                a = self.i
                if ws and s.startswith("((", a) and (a, None) not in self.not_arith:
                    state = self._snapshot(None)
                    self.i = a + 2
                    if self._arith(None, ")"):
                        ws, cmd = True, False
                        continue
                    self._restore(state, None)   # "(("로 시작하지만 산술이 아니다: 겹친 하위 셸
                    self.not_arith.add((a, None))
                self.i = a + 1
                if a > 0 and s[a - 1] in "<>":
                    self._comsub()               # <( ) 와 >( ): 낱말의 일부다
                    ws = cmd = False
                elif ws:
                    self._code("paren")          # 하위 셸
                    ws, cmd = True, False
                else:
                    empty = s.startswith(")", a + 1)
                    self._code("paren")          # 이름=( ) 배열, 함수 정의의 ( ): 낱말에 붙은 괄호
                    ws, cmd = False, empty
                continue
            if c == ")":
                self.i += 1
                if mode in ("cmdsub", "paren") and case_depth == 0:
                    self._leave()
                    return
                ws, cmd = True, case_depth > 0   # case 무늬를 닫는 괄호 뒤는 명령 자리다
                continue
            if c == "}" and ws and mode == "brace":
                self.i += 1
                self._leave()
                return
            if c == "<" and s.startswith("<<", self.i):
                if s.startswith("<<<", self.i):
                    self.i += 3
                    ws = True
                    continue
                j = self.i + 2
                strip_tabs = j < n and s[j] == "-"
                if strip_tabs:
                    j += 1
                while j < n and (s[j] in " \t" or s.startswith("\\\n", j)):
                    j += 2 if s[j] == "\\" else 1
                delim, quoted, j_end = self._heredoc_word(j)
                if delim or quoted:
                    self.pending.append((delim, strip_tabs, quoted))
                    self.i = j_end
                else:
                    self.i += 2
                ws = True
                continue
            if c in ";|&":
                self.i += 1
                ws = cmd = True
                continue
            if c in "<>":
                self.i += 1
                ws = True
                continue
            if ws:
                j = self.i
                while j < n and s[j] not in _WORD_END:
                    j += 1
                word = s[self.i:j]
                if cmd and word in _COMMAND_STARTERS:
                    self.i = j
                    ws = False               # 이 낱말들 뒤는 여전히 명령 자리다
                    continue
                if cmd and word == "case":
                    await_in += 1
                    self.i = j
                    ws = cmd = False
                    continue
                if await_in and word == "in":
                    await_in -= 1
                    case_depth += 1
                    self.i = j
                    ws = cmd = False
                    continue
                if cmd and case_depth and word == "esac":
                    case_depth -= 1
                    self.i = j
                    ws = cmd = False
                    continue
                if cmd and word == "[[":
                    cond = True
                    self.i = j
                    ws = cmd = False
                    continue
                if "[" in word:
                    k = self.i
                    while k < n and (s[k].isalnum() or s[k] == "_"):
                        k += 1
                    if self.i < k < n and s[k] == "[" and not s[self.i].isdigit():
                        # 이름[첨자]=값: 첨자는 산술식이다(그 안의 "<<"는 히어독이 아니고, 작은따옴표는 막아 주지 않는다)
                        state, start = self._snapshot(None), self.i
                        self.i = k + 1
                        if self._arith(None, "]") and (s.startswith("=", self.i) or s.startswith("+=", self.i)):
                            ws = cmd = False
                            continue
                        self._restore(state, None)
                        self.i = start
                cmd = False
            self.i += 1
            ws = False
        self._leave()

    def run(self) -> None:
        try:
            self._code("top")
        except (_GiveUp, RecursionError):
            self.gave_up = True        # 여기까지 찾은 것은 남긴다


def _by_index(item):
    return item[1]


def scan(text: str, pid_paren_nests: bool = False, deadline=None):
    """한 가지 표기를 한 가지 방식으로 읽어 (위반 목록, 실행되는 치환 목록)을 위치 순서로 돌려준다.
    위반: (규칙, 위치, 자리 설명). 치환: (종류, 위치). 역슬래시 접기와 CR 빼기는 하지 않는다.
    너무 깊거나 오래 걸려 그만둔 경우에도 그때까지 찾은 것을 돌려준다."""
    sc = _Scanner(text, pid_paren_nests, deadline)
    sc.run()
    return sorted(set(sc.found), key=_by_index), sorted(set(sc.active), key=_by_index)


def read_both_ways(text: str, deadline=None):
    """scan()과 같되, 글에 "$$("가 있으면 그것을 읽는 두 방식의 결과를 합친다."""
    found, active = scan(text, False, deadline)
    if "$$(" in text:
        found2, active2 = scan(text, True, deadline)
        found = sorted(set(found) | set(found2), key=_by_index)
        active = sorted(set(active) | set(active2), key=_by_index)
    return found, active


def _excerpt(text: str, index: int, width: int = 34) -> str:
    a, b = max(0, index - width), min(len(text), index + width)
    near = "".join(ch if ch >= " " and ch != "\x7f" else " " for ch in text[a:b])
    return ("..." if a > 0 else "") + near + ("..." if b < len(text) else "")


def find_violations(command: str, strict: bool = False) -> list:
    """명령에서 위반을 찾아 위치 순서로 돌려준다. 찾지 못하면 빈 목록(통과)이다.
    원문에 위반이 있으면 그것을, 없으면 역슬래시가 접힌 표기의 위반을 돌려준다.
    두 표기를 모두 읽어야 한다: 짧은 명령은 접혀서, 긴 명령은 원문 그대로 Bash에 도착한다.
    strict가 거짓이면 규칙 A(백틱)만 본다."""
    if "`" not in command and not (strict and "$(" in command):
        return []
    variants = [(AS_WRITTEN, as_bash_reads(command))]
    folded = as_bash_reads(fold_backslashes(command))
    if folded != variants[0][1]:
        variants.append((FOLDED, folded))
    deadline = time.perf_counter() + TIME_BUDGET
    for variant, text in variants:
        found, _active = read_both_ways(text, deadline)
        if not strict:
            found = [f for f in found if f[0] == RULE_BACKTICK]
        if found:
            line_starts = [0]
            pos = text.find("\n")
            while pos >= 0:
                line_starts.append(pos + 1)
                pos = text.find("\n", pos + 1)
            out = []
            for rule, index, where in found:
                line = bisect.bisect_right(line_starts, index)
                col = index - line_starts[line - 1] + 1
                out.append(Violation(rule, index, line, col, where, variant, _excerpt(text, index)))
            return out
    return []


def format_message(violations: list) -> str:
    lines = ["[bash-quote-guard] BLOCKED [backtick-check-hook] before running."]
    for v in violations[:4]:
        what = ("backtick command substitution" if v.rule == RULE_BACKTICK
                else "dollar-parenthesis substitution mixed into text")
        lines.append(f"- line {v.line}, col {v.col} ({v.where}): {what}")
        lines.append(f"    near: {v.near}")
    if len(violations) > 4:
        lines.append(f"- and {len(violations) - 4} more")
    if violations and violations[0].variant == FOLDED:
        lines.append("The Windows launcher may fold backslashes in short commands. "
                     "Here the text as you typed it is clean; the positions refer to the folded form.")
    lines += [
        "Write literal text or code directly to a file with a file-writing tool. "
        "For literal shell arguments use single quotes or a quoted here-document delimiter.",
        "When other expansions are needed in double quotes, put exactly ONE backslash before a literal backtick. "
        "Run PowerShell code in PowerShell. For intentional Bash command substitution use $(...).",
    ]
    if any(v.rule == RULE_DOLLAR_PAREN for v in violations):
        lines.append("In strict mode separate substitutions from literal text, for example by assigning the output first.")
    lines += [
        "[한국어] 실행 전에 막았습니다. Bash가 이 위치의 글을 명령으로 치환할 수 있습니다.",
        "글·코드는 파일 쓰기 도구로 파일에 직접 쓰세요. 짧은 글은 작은따옴표나 따옴표 붙인 히어독을 쓸 수 있습니다.",
    ]
    return "\n".join(lines) + "\n"


def _block_code(argv) -> int:
    for arg in argv:
        if arg.startswith("--block-code="):
            try:
                code = int(arg.split("=", 1)[1])
            except ValueError:
                continue
            if 1 <= code <= 255:
                return code
    return 2


def _self_test_shell():
    """Use the documented host shell for the outer declaration."""
    import os
    from pathlib import Path
    if os.name != "nt":
        return "/bin/sh" if os.access("/bin/sh", os.X_OK) else None
    sysroot = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    cwd = Path.cwd().resolve()
    if override := os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"):
        cands = [Path(override)]
    else:
        cands = [Path(root) / "Git/bin/bash.exe" for key in ("ProgramW6432", "ProgramFiles")
                 if (root := os.environ.get(key))]
        for directory in os.get_exec_path():
            path = Path(directory)
            if path.is_absolute() and not path.resolve().is_relative_to(cwd):
                cands.append(path / "bash.exe")
                if (path / "git.exe").is_file():
                    cands.append(path.parent / "bin/bash.exe")
    for cand in cands:
        if not cand.is_absolute() or not cand.is_file():
            continue
        path = cand.resolve()
        if (sysroot and path.is_relative_to(Path(sysroot).resolve())) or "windowsapps" in (part.lower() for part in path.parts):
            continue
        git_root = path.parent.parent
        if git_root.name.lower() == "usr":
            git_root = git_root.parent
        if path.name.lower() == "bash.exe" and path.parent.name.lower() == "bin" and (git_root / "cmd/git.exe").is_file():
            return str(path)
    return None


def _matcher_covers(matcher: str, tool: str):
    """Claude Code가 훅의 matcher를 읽는 규칙을 따른다.
    비었거나 "*"이면 모든 도구. 글자·숫자·밑줄·"|"로만 되어 있으면 이름 목록. 그 밖에는 정규식이고 도구 이름의
    어디든 맞으면 된다. 정규식이 틀렸으면 그 훅은 아예 돌지 않는다(None을 돌려준다)."""
    import re
    if matcher in ("", "*"):
        return True
    if re.fullmatch(r"[A-Za-z0-9_|]+", matcher):
        return tool in matcher.split("|")
    try:
        return re.search(matcher, tool) is not None
    except re.error:
        return None


def self_test(settings_paths=None, bash=None, env=None, budget: float = 8.0, installed=False) -> list:
    """설정에 걸린 이 검사기의 훅 명령을 실제로 돌려 본다. 문제를 적은 문장 목록을 돌려준다(빈 목록이면 정상).
    "note: "로 시작하는 문장은 알림이다: 그 문제가 있어도 두 도구는 동작하는 훅으로 덮여 있다.
    플러그인은 자체 선언, 사용자 설치본은 실제 등록과 설치 영수증을 대조한다."""
    import os
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    owned_commands = None
    if settings_paths is None:
        receipt = root / "state.json"
        if installed or receipt.is_file():
            try:
                state = json.loads(receipt.read_bytes())
                if state["host"] != "claude" or state["format"] != 1:
                    raise ValueError()
                owned_commands = {handler["command"] for group in state["entries"]["PreToolUse"]
                                  for handler in group["hooks"]}
            except (OSError, KeyError, TypeError, ValueError):
                return ["cannot identify the installed Bash hook from its receipt"]
            settings_paths = [str(root.parent / "settings.json")]
        else:
            settings_paths = [str(root / "hooks" / "hooks.json")]
    env = dict(os.environ if env is None else env)
    env["CLAUDE_PLUGIN_ROOT"] = root.as_posix()
    unreadable, entries, seen = [], [], set()
    for path in settings_paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception:
            unreadable.append("settings file is not valid JSON, so none of its hooks run: %s" % path)
            continue
        found = ((data.get("hooks") or {}).get("PreToolUse") or []) if isinstance(data, dict) else []
        for entry in found if isinstance(found, list) else []:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks") or []:
                command = hook.get("command") if isinstance(hook, dict) else None
                if owned_commands is not None and (not isinstance(command, str) or command not in owned_commands):
                    continue
                if isinstance(command, str) and GUARD_FILE in command and hook.get("type") == "command":
                    key = (str(entry.get("matcher") or ""), command, bool(hook.get("async")))
                    if key not in seen:        # 같은 항목이 두 설정에 있으면 Claude Code도 한 번만 돌린다
                        seen.add(key)
                        entries.append({"path": path, "matcher": key[0], "hook": hook, "problems": []})
    if not entries:
        return unreadable + ["no PreToolUse hook runs %s (looked in: %s)" % (GUARD_FILE, ", ".join(settings_paths))]
    bash = bash or _self_test_shell()
    if not bash:
        return unreadable + ["the host shell was not found (Git Bash on Windows, /bin/sh on POSIX)"]

    def payload(tool, command):
        return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                           "tool_input": {"command": command}}).encode("utf-8")

    live = 'echo "self-test ' + "`" + "true" + "`" + ' text"'          # 훅에 글로만 넘긴다. 실행하지 않는다
    dead = "echo 'self-test " + "`" + "not run" + "`" + " text'"
    started = []                           # 세션 시작을 늦추지 않게 한꺼번에 띄우고 차례로 거둔다
    for entry in entries:
        covers = {tool: _matcher_covers(entry["matcher"], tool) for tool in TOOL_NAMES}
        entry["covers"] = [tool for tool in TOOL_NAMES if covers[tool]]
        if None in covers.values():
            entry["problems"].append('the matcher "%s" in %s is not a valid pattern, so that hook never runs'
                                     % (entry["matcher"], entry["path"]))
        if entry["hook"].get("async"):
            entry["problems"].append("the hook in %s is marked async, so it cannot block a command" % entry["path"])
        first = entry["covers"][0] if entry["covers"] else TOOL_NAMES[0]
        tries = [(tool, live, 2) for tool in entry["covers"]] + [(first, dead, 0), (first, "echo plain text", 0)]
        for tool, command, want in tries:
            try:
                proc = subprocess.Popen([bash, "-c", entry["hook"]["command"]], stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
                proc.stdin.write(payload(tool, command))
                proc.stdin.close()
                started.append((entry, tool, want, proc, None))
            except Exception as exc:
                started.append((entry, tool, want, None, exc.__class__.__name__))
    deadline = time.monotonic() + budget   # 기다리는 시간은 모두 합쳐 budget을 넘지 않는다
    for entry, tool, want, proc, failure in started:
        where = "the hook in %s" % entry["path"]
        if proc is None:
            entry["problems"].append("%s could not be run (%s)" % (where, failure))
            continue
        try:
            got = proc.wait(timeout=max(0.05, deadline - time.monotonic()))
        except Exception:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            entry["problems"].append("%s did not finish within %g seconds" % (where, budget))
            continue
        if got == want:
            continue
        if want == 2:
            entry["problems"].append("%s did not block a command with a live backtick (tool %s: exit %s)"
                                     % (where, tool, got))
        elif got == 2:
            entry["problems"].append("%s blocked a harmless command (tool %s)" % (where, tool))
        else:
            entry["problems"].append("%s ended with exit %s on a harmless command (tool %s, expected 0)"
                                     % (where, got, tool))
    working = [entry for entry in entries if not entry["problems"]]
    uncovered = [tool for tool in TOOL_NAMES if not any(tool in entry["covers"] for entry in working)]
    problems = ["no working hook covers the %s tool" % tool for tool in uncovered]
    prefix = "" if uncovered else "note: "  # 두 도구가 모두 덮여 있으면 나머지는 알림이다
    problems += [prefix + text for text in unreadable]
    for entry in entries:
        for text in dict.fromkeys(entry["problems"]):
            problems.append(prefix + text)
    commands = {entry["hook"]["command"] for entry in entries}
    if len(commands) > 1:
        problems.append("note: %d different guard commands are wired, so the check runs more than once per call"
                        % len(commands))
    return problems


def format_self_test(problems: list) -> str:
    notes_only = all(problem.startswith("note: ") for problem in problems)
    if notes_only:
        lines = ["[bash-quote-guard] NOTICE: the Bash backtick guard works in this session, but its setup has a problem."]
    else:
        lines = ["[bash-quote-guard] WARNING: the Bash backtick guard is NOT fully protecting this session."]
    lines[0] += " [backtick-check-hook]"
    lines += ["- " + (problem[6:] if problem.startswith("note: ") else problem) for problem in problems]
    if not notes_only:
        lines += ["Until this is fixed, do not put text that contains backticks inside double quotes or unquoted",
                  "here-documents: write it to a file with a file-writing tool."]
    lines.append("See the installation and self-test sections in README.md.")
    if notes_only:
        lines.append("[한국어] Bash 백틱 검사 훅은 동작하지만 설정에 위 문제가 있습니다. 이 내용을 사용자에게 알리세요.")
    else:
        lines += ["[한국어] Bash 백틱 검사 훅이 이 세션을 다 막아 주지 못합니다. 고쳐질 때까지 백틱이 든 글·코드는",
                  "  파일 쓰기 도구로 파일에 쓰고, 이 경고를 사용자에게 알리세요."]
    lines.append("  설치와 자가 점검 방법은 README.ko.md에 있습니다.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        try:
            problems = self_test(installed="--installed" in argv)
        except Exception as exc:
            problems = ["the self-test itself failed: %s" % exc.__class__.__name__]
        if not problems:
            return SELF_TEST_OK
        try:
            sys.stdout.buffer.write(format_self_test(problems).encode("utf-8", "backslashreplace"))
            sys.stdout.flush()
        except Exception:
            pass
        return SELF_TEST_FAILED
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
        violations = find_violations(command, strict="--strict" in argv)
        if not violations:
            return 0
        message = format_message(violations)
    except Exception:   # 검사기 고장이 작업을 막지 않게 한다
        return 0
    try:
        sys.stderr.buffer.write(message.encode("utf-8", "backslashreplace"))
        sys.stderr.flush()
    except Exception:
        try:   # 이유 없이 막히는 일이 없게, 글자를 못 쓰면 고정 문장이라도 남긴다
            sys.stderr.buffer.write(b"[bash-quote-guard] BLOCKED [backtick-check-hook]: a live backtick in the command. "
                                    b"Write the text to a file or use single quotes.\n")
            sys.stderr.flush()
        except Exception:
            pass
    return _block_code(argv)


if __name__ == "__main__":
    sys.exit(main())
