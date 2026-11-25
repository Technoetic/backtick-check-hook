# Backtick Check Hook

코딩 도구가 셸에 넘기는 글에서 백틱 때문에 마크다운이나 명령문이 달라지는 경우를 검사한다. Bash에서는 명령 치환 위치를, PowerShell에서는 Git·GitHub CLI로 글을 쓰는 명령 안의 활성 백틱을 찾는다. PowerShell 출력 명령의 정상 탭 이스케이프는 통과한다.

[English](README.md) · [보안과 신뢰](SECURITY.md) · [변경 기록](CHANGELOG.md)

## 설치와 확인

사용자가 관리하는 설치 폴더와 Python 3.10 이상을 준비한다. 패키지 루트에서 원하는 호스트를 지정한다. Windows Codex의 예는 다음과 같다.

~~~powershell
python -I -X utf8 -B install.py install --host codex
python -I -X utf8 -B install.py doctor --host codex
~~~

호스트 이름은 **claude**, **codex**, **antigravity**다. Windows 런처를 쓰면 **py -3**, POSIX에서는 **python3**로 시작한다. 설치에 사용한 인터프리터의 절대 경로를 등록한다. 설치기는 사용자 설정 파일 옆 **backtick-check-hook** 폴더에 실행 파일과 라이선스를 복사하고 해당 처리기를 등록한다. 기존 등록이나 설치 파일을 누군가 수정했으면 충돌을 보고한다. 설정 파일의 원래 서식까지 복원하려면 설치 전 사본을 보관한다.

| 호스트 | 설치 위치와 처리 방식 | 설치 뒤 할 일 |
|---|---|---|
| Claude Code | 사용자 설정에 등록하거나 패키지 자체의 플러그인 매니페스트로 불러온다. Bash·Monitor는 Bash 검사기, PowerShell은 게시 검사기를 쓴다. Windows의 사전 검사는 Git Bash로 실행한다. 검사기 종료 42는 훅 종료 2로, 나머지 종료 코드는 0으로 바꾼다. | 두 방식 중 하나를 선택한 뒤 새 대화를 연다. SessionStart에서 설치된 Bash 훅 명령에 합성 이벤트를 넣는다. 내부 자가 점검의 정상값은 10이다. 바깥 훅은 문제가 있을 때 경고하고 종료 0으로 끝난다. |
| Codex | 사용자 PreToolUse에 Bash 도구 이름을 등록한다. Windows 어댑터는 Windows PowerShell로 돌고, 차단 시 deny JSON과 종료 0을 반환한다. 호스트 제한은 30초다. | 실행 중인 화면의 **/hooks**에서 신뢰한다. 다른 프로세스에서 등록했다면 Codex를 다시 띄우거나 VS Code 창을 다시 불러온다. 새 부모 대화와 거기서 만든 하위 대화에서 탐침을 보낸다. 별도 hooks/list는 조회한 프로세스의 상태를 보여 준다. |
| Antigravity | 사용자 hooks.json의 이름 붙은 항목이 **run_command**와 **manage_task**의 입력 전달을 검사한다. Windows에서는 cmd /c가 어댑터를 띄운다. 차단은 deny JSON, 통과는 빈 표준 출력과 종료 0이다. 실행기 오류는 Windows 명령 래퍼가 종료 0으로 처리한다. | 새 대화를 열고, 기존 대화에 적용하려면 사용자가 허브를 다시 시작한다. 판이 바뀌면 탐침을 반복한다. 같은 훅을 두 곳에 등록하면 두 번 돌 수 있다. |

Claude Code에서는 **claude --plugin-dir** 뒤에 패키지 절대 경로를 주는 방법도 있다. 수정 가능한 프로젝트 밖의 신뢰하는 폴더를 사용한다. 설치기의 기본 대상은 사용자 전역 설정이다. 작업 공간의 훅은 그 프로젝트를 바꿀 수 있는 사람이 수정할 수 있다. Codex·Antigravity는 POSIX에서 Bash로 보내지만 Linux·macOS의 실제 호스트 셸 선택은 **미측정**이다. Windows에서는 요청의 셸 힌트와 실제 실행기가 다를 수 있어 두 어댑터가 PowerShell 검사기를 쓴다.

**doctor**는 등록 항목·인터프리터·설치 파일 해시와 합성 이벤트를 검사한다. 실제 새 대화에서 아래 탐침을 확인한 사용자는 **record-probe --host HOST --host-version VERSION**으로 확인한 판을 남길 수 있다. 이후 **doctor --host-version VERSION**에 현재 실행 중인 판을 넘겨 비교한다. 디스크에 설치된 판과 실행 중인 판은 다를 수 있다. Codex의 신뢰 해시는 선언을 덮는다. 선언을 변경하면 재신뢰하고, 어댑터·검사기 파일 변경도 훅 변경으로 검토한다.

설치기는 Codex·Antigravity의 사용자 훅 선언에 등록한다. Codex 네이티브 플러그인의 신뢰 검토는 번들 스크립트의 변경도 대상으로 삼을 수 있다. Antigravity 네이티브 플러그인은 루트 hooks.json과 플러그인 루트 기준의 상대 경로를 지원한다. 이 설치기는 복사된 파일의 절대 경로를 등록한다. [Codex 훅 신뢰](https://developers.openai.com/codex/hooks/) · [Antigravity 플러그인 구조](https://antigravity.google/docs/build-plugins.md)

## 호스트 탐침

한 줄씩 별도의 셸 도구 호출로 보낸다. Windows PowerShell에서는 다음 세 줄을 쓴다.

~~~powershell
if ($false) { gh release create v0.0.0-probe --notes "probe `x` text" }
Write-Output "a`tb"
echo plain
~~~

첫 호출에서 **[backtick-check-hook]**과 위치 1:61, 1:63을 확인한다. 거짓 분기여서 릴리스 명령은 실행되지 않는다. 다음 두 줄은 각각 a와 b 사이 탭 하나, plain을 출력하고 종료 0이어야 한다. 다른 훅이 먼저 막았으면 어느 훅이 작동했는지 구분할 수 없다. Bash에서는 아래 첫 줄의 차단 표지와 나머지 두 줄의 문자 그대로 출력을 확인한다.

~~~bash
if false; then echo "probe `x` text"; fi
echo 'literal `x`'
echo plain
~~~

### 실제 호스트 측정

| 호스트 | 실행 중인 판 | 모드 | OS | 실행 셸 | 날짜 / 후보 커밋 | 결과 |
|---|---|---|---|---|---|---|
| Claude Code | — | — | — | — | — | 미시험 |
| Codex | — | — | — | — | — | 미시험 |
| Antigravity | — | — | — | — | — | 미시험 |

실제 대화에서 후보 패키지를 불러와 탐침을 확인한 경우에 이 표에 기록한다. 어댑터 시험에서는 통제된 입력을 쓴다. 이전 어댑터의 빈 출력·빈 JSON 객체 관측은 Antigravity CLI 1.5.17의 검토·자동 모드에서 얻었다. 빈 출력의 의미는 실측에 근거하고, 호스트 시간 초과 동작은 미측정이다. Codex 하위 대화의 부모 설정 상속은 소스로 확인한 동작이다. 재시작 전후 대조에서는 서버·대화·시각이 함께 바뀐다.

## 남는 틈과 과잉 차단

- **Bash 문법.** 작은따옴표·ANSI-C 인용 문자열·구분자를 인용한 히어독·주석·역슬래시 하나로 이스케이프한 백틱은 일반적으로 글자로 읽는다. 기본값에서는 달러-괄호 명령 치환을 허용하고 선택형 strict 검사에서 일부 혼합 문자열을 검사한다. 별도로 인용해 넘긴 셸이나 SSH의 안쪽 스크립트, 조용히 글이 바뀌는 변수 치환에는 검사가 미치지 않는다.
- **Bash의 보수적 판정.** 원문과 역슬래시를 접은 글을 함께 검사하고 Windows에서는 Git Bash가 CR을 버리는 동작도 반영한다. 다른 실행기에서는 이 때문에 더 막을 수 있다. 배열 첨자는 실행 때의 변수 종류에 따라 뜻이 달라지고 미완성 히어독 뒤의 글은 해석이 모호하다. 깊이 150 또는 3초 예산에서 읽기를 멈추면 그때까지의 결과로 판정한다. SessionStart는 시작·재개·clear·compact·fork 때 선언된 Bash·Monitor 처리기를 확인한다. 호스트가 훅 실행을 통째로 끈 경우나 점검 사이의 변경, 훅이 호출되지 않은 경우를 지속적으로 감시하지 않는다.
- **PowerShell 인식 범위.** gh release·pr·issue·api와 git commit·tag·notes·merge의 일반적인 글쓰기 꼴을 본다. 앞선 호출에서 이미 깨진 파일, 스크립트 파일 안의 명령, 스플래팅·변수로 구성한 인자·동적 명령·Start-Process·인코딩한 명령·생성한 스크립트 블록은 놓칠 수 있다. gh repo edit --description, gh secret set --body, git stash -m, git commit-tree 등은 인식 목록 밖이다. 한 셸에서 다른 셸을 띄운 경우, Codex의 대화형 write_stdin, Antigravity에서 다른 종류의 셸로 전달한 입력도 따로 확인한다.
- **PowerShell 문법과 상한.** 명령 낱말 사이 주석, 식 직후 주석 안 작은따옴표, 달러 기호 직후의 블록 주석 시작, 괄호로 쓴 옵션 값, 생략하거나 줄을 나눈 -Command, 3단을 넘는 간접 평가는 놓칠 수 있다. tag·merge의 붙여 쓴 메시지 옵션과 축약형도 놓칠 수 있다. Git 동사 앞 옵션은 32개까지 읽고 일부 동사 뒤 플래그 검색은 4,000자로 제한한다. 백틱과 인식된 게시 동작이 있는 명령이 400,000자를 초과하거나 읽기를 끝내지 못하면 보수적으로 막을 수 있다.
- **한 호출 전체를 보아 생기는 차단.** 주석·인용문 안에 적은 게시 명령, 다른 곳의 간접 평가, 파일을 넘기는 커밋과 무관한 이스케이프, --no-edit를 붙인 amend가 섞여도 막을 수 있다. 식에 붙은 주석과 PowerShell 구문 분석 중지 토큰 뒤의 글을 일반 인자로 읽을 수 있다. 읽기 전용 gh api 뒤의 -First·-Force·-Filter·-FilePath가 필드 쓰기로 인식되거나, 읽기 전용 git tag·notes가 다른 문장의 낱말이나 스위치와 맞을 수 있다. 이 판에서는 기존 판정을 유지한다. 서로 다른 작업은 호출을 나누고 게시 본문은 파일 쓰기 도구로 작성한 뒤 파일명으로 넘긴다.
- **실패와 비용.** 훅이 없거나 미신뢰일 때, 인터프리터가 없을 때, 이벤트 해석 또는 처리에 실패할 때는 검사가 빠질 수 있다. Codex는 제한 시간이 지나면 호출을 진행할 수 있다. Claude와 Antigravity의 PreToolUse 선언은 15초다. Claude는 이벤트에 백틱 표지가 없으면 Python을 시작하지 않는다. Windows Codex는 셸 호출마다 PowerShell을, Antigravity는 Python 어댑터를 띄운다. 3.11 미만 Python의 대체 정규식은 줄 이음이 반복될 때 더 느릴 수 있다.

### 로컬 실행기 소요 시간

**Python 3.10 호환성 문제.** PowerShell 검사기가 Python 3.10용 대체 정규식을 사용할 때 기존 CRLF 줄 이음 속도 시험의 원래 한계 0.5초를 초과한다. Windows 시험 실행기는 3.10의 원래 속도 시험을 각각 자식 프로세스에서 실행해 8초를 초과하면 실패로 집계하고 나머지 시험을 이어간다. 후보의 실행에는 Python 3.11 이상을 권장한다.

Windows에서 평문 이벤트를 예열 뒤 일곱 번 측정한 중앙값은 Git Bash 사전 검사와 cmd/Python 어댑터에서 각각 0.5초 미만, cmd/PowerShell 어댑터에서 0.2~2초였다. 임시 홈의 설정에서 읽은 명령의 시작부터 종료까지 잰 합성 측정이다. 바깥 셸만 띄운 빈 호출도 따로 재고, 추가 비용은 두 중앙값의 차이로 본다. 실제 대화의 지연은 미측정이다. Python 어댑터를 하나로 합치면 Windows Codex의 평문 경로에서도 Python을 띄우게 되고 호스트별 응답 형식은 여전히 따로 처리해야 한다.

## 제거와 시험

사용자가 설치한 항목은 **python install.py uninstall --host HOST**로 제거한다. 설치 영수증과 파일을 확인한 뒤 소유한 항목을 제거한다. Claude 훅의 셸 문법 오류 때문에 Bash 도구가 계속 막히면 플러그인 화면이나 텍스트 편집기로 해당 등록을 해제하고 대화를 다시 연다. Bash 자체의 문법 오류 종료 값 2를 Claude가 차단으로 해석할 수 있다. 별도로 등록한 플러그인이나 작업 공간 훅에는 그 소유자의 조치가 필요하다.

Windows 전체 시험은 **python -B tools/test_windows.py 65001**과 **python -B tools/test_windows.py 949**로 전용 콘솔에서 실행한다. 임시 홈에 설치한 명령을 시험하고 Bash 5.3 구문을 실제 Git Bash와 대조한다. Git Bash·PowerShell 7을 준비하면 해당 시험을 실행할 수 있다. Windows PowerShell 5.1도 별도로 확인한다. 릴리스·커밋 본문은 파일 편집기로 써서 **--notes-file**, **--body-file**, **git commit -F**로 넘긴다.
