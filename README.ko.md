# Backtick Check Hook

코딩 도구가 마크다운 예시를 셸로 보낼 때 백틱 때문에 내용이 달라질 수 있다. 이 훅은 Bash의 명령 치환과 Git·GitHub CLI로 글을 쓰는 PowerShell 명령 안의 활성 백틱을 검사한다. 일반 출력 명령에 쓰는 PowerShell 탭 이스케이프는 통과한다.

[English](README.md) · [보안과 신뢰](SECURITY.md) · [변경 기록](CHANGELOG.md)

## 설치와 확인

신뢰하는 패키지 사본과 사용자가 관리하는 **Python 3.11 이상**을 사용한다. 설치기는 Python 3.10 이하를 거부한다. 패키지 최상위 폴더에서 사용할 호스트를 지정한다. 다음 두 명령은 Windows에서 Codex 훅을 등록하고 확인한다.

~~~powershell
python -I -X utf8 -B install.py install --host codex
python -I -X utf8 -B install.py doctor --host codex
~~~

`--host` 값은 `claude`, `codex`, `antigravity` 중 하나다. Windows Python 런처를 사용한다면 `python`을 `py -3`으로 바꾼다. POSIX에서는 `python3`를 사용한다. 설치기는 자신을 실행한 인터프리터를 등록하고, 호스트에 필요한 파일과 라이선스를 사용자 설정 옆 `backtick-check-hook` 폴더에 복사한 뒤 사용자 설정에 처리기를 등록한다. 설치·제거 시 기존 파일이나 설정의 편집 내용이 충돌하는지 검사한다. 설정 파일의 서식까지 복원하려면 설치 전 사본을 보관한다.

| 호스트 | 설치 위치와 처리 방식 | 설치 뒤 할 일 |
|---|---|---|
| Claude Code | **Windows에서 이 훅을 쓰려면 Git Bash가 필요하다.** Git Bash가 없으면 설치기가 등록을 거부한다. POSIX에서는 호스트의 `sh -c`가 절대 경로 `/bin/bash`를 실행한다. Bash·Monitor는 Bash 검사기를, PowerShell은 게시 검사기를 쓴다. 이 지원 경로에서 검사기 종료 42는 훅 종료 2(차단)가 되고, 나머지 검사기 종료 값은 래퍼가 0으로 바꾼다. | 사용자 설정 등록과 네이티브 플러그인 중 하나를 선택한다. 새 대화를 열고 아래 확인 명령을 실행한다. SessionStart 때 사용자 설치본은 `settings.json`에 등록된 처리기를, 네이티브 플러그인은 자체 `hooks/hooks.json`의 처리기를 시험한다. 자가 점검의 정상 종료 값은 10이다. 바깥 래퍼는 자가 점검 실패나 실행기 누락을 알리고 종료 0으로 끝난다. |
| Codex | 사용자 PreToolUse 훅이 `Bash` 도구 이름에 일치한다. Windows에서는 Windows PowerShell이 어댑터를 실행한다. 차단 시 JSON을 반환하고 종료 0으로 끝난다. 호스트 시간 제한은 30초다. | 실행 중인 클라이언트에서 선언을 신뢰한다. CLI에서는 `/hooks`를 열고, 데스크톱 앱에서는 **Review hooks** 또는 **Settings → Hooks**를 선택한다. 별도 프로세스가 신뢰를 기록했다면 Codex를 다시 시작하거나 VS Code 창을 다시 불러온다. 새 대화와 그 안에서 만든 하위 대화에서 확인 명령을 실행한다. 별도 `hooks/list` 조회는 조회한 프로세스의 상태를 보여 준다. |
| Antigravity | 사용자 `hooks.json`의 이름 있는 항목이 `run_command`와 `manage_task` 입력 전달을 처리한다. Windows CLI 1.5.17에서는 `cmd /c`가 쓰였고, 표준 출력이 비어 있고 종료 값이 0이면 통과하는 동작이 관측됐다. 어댑터는 차단 시 JSON을 반환한다. Windows 래퍼는 실행기 오류 시 종료 0으로 끝난다. | 새 대화를 연다. 기존 대화에 반영하려면 허브를 다시 시작한다. 업데이트 뒤 확인 명령을 다시 실행한다. 같은 훅을 중복 등록하면 두 번 실행될 수 있다. |

여러 대화에 걸쳐 등록을 유지하려면 설치기를 사용한다. 설치기는 사용자 수준의 등록만 처리한다. Claude Code 대화 하나에서 네이티브 플러그인을 쓰려면 `claude --plugin-dir` 뒤에 패키지 절대 경로를 준다. 이 방식도 Windows에서는 Git Bash가 필요하다. POSIX에서 Claude를 쓰는 두 방식 모두 `/bin/sh`와 `/bin/bash`가 필요하다. 편집 가능한 프로젝트 밖의 신뢰하는 폴더를 사용한다. 프로젝트 파일을 바꿀 수 있는 사람은 프로젝트에 등록된 훅도 바꿀 수 있다. Windows에서 Codex와 Antigravity의 등록은 요청에 다른 셸 힌트가 있어도 PowerShell 검사기를 선택한다. POSIX에서 두 등록은 Bash 검사기를 선택한다. Linux·macOS 실제 대화의 셸 선택은 미측정이다.

`doctor`는 등록 상태, 인터프리터 실행 가능 여부, 설치 파일 해시, 합성 이벤트를 검사한다. Python이 3.11 미만이면 경고한다. 통과 결과는 설치된 훅 명령의 동작에 관한 것이다. 새 호스트 대화에서 아래 확인 명령을 실행한 뒤 `record-probe --host HOST --host-version VERSION`으로 실행 중인 호스트 버전을 기록한다. 나중에 다시 검사할 때는 실행 중인 버전을 `doctor --host HOST --host-version VERSION`에 넘긴다. 디스크에 설치된 버전과 실행 중인 버전은 다를 수 있다. Codex의 신뢰 해시는 선언을 대상으로 한다. 선언·어댑터·검사기의 변경을 검토하고, 선언을 편집했다면 신뢰를 다시 등록한다.

Claude의 PreToolUse 선언은 훅 실행 오류 처리에 `onFailure`의 `continue` 값을 쓴다. 의도적인 종료 2는 호출을 차단한다. 이 옵션은 Claude Code 2.1.295 이상에서 지원한다. 오프라인 엄격 검증에서 2.1.248과 2.1.252는 이 값과 유효하지 않은 값을 모두 받아들였고, 2.1.330은 유효하지 않은 값을 거부했다. 이전 버전의 실제 대화에서 이 필드를 처리하는 방식은 미확인이다. [Claude Code 훅 참조](https://code.claude.com/docs/en/hooks)

이 설치에서 Codex와 Antigravity는 사용자 훅 선언을 쓴다. Codex 네이티브 플러그인의 신뢰 검토는 번들 스크립트 변경도 대상으로 삼을 수 있다. Antigravity 네이티브 플러그인은 루트의 `hooks.json`과 그 루트를 기준으로 한 상대 경로를 지원한다. 이 설치기는 설치 파일의 절대 경로를 등록한다. [Codex 훅 신뢰](https://developers.openai.com/codex/hooks/) · [Antigravity 플러그인 구조](https://antigravity.google/docs/build-plugins.md)

## 호스트 탐침

Windows에서 `doctor`는 설치된 Codex 훅 명령을 cmd와 PowerShell 양쪽에서 실행한다. 어댑터와 인터프리터의 경로에는 공백과 비ASCII 문자를 쓸 수 있다. 두 실행기에서 모두 안전하게 인용할 수 없는 경로 문자(퍼센트·느낌표·달러·백틱 등)는 설치기가 거부한다. Antigravity에는 셸에서 따옴표 없이 쓸 수 있는 절대 경로나 같은 파일을 가리키는 Windows 8.3 짧은 이름을 쓴다. 둘 다 쓸 수 없으면 설치를 거부한다. Antigravity 점검은 cmd에 원시 명령줄을 넘기는 방식과 인자 목록을 넘기는 방식을 모두 실행한다. 실제 호스트가 인자를 전달하는 방식은 미측정이다.

각 줄을 별도의 셸 도구 호출로 보낸다. Claude의 PowerShell 도구 또는 Windows용 Codex·Antigravity의 PowerShell 경로에서는 다음 명령을 사용한다.

~~~powershell
if ($false) { gh release create v0.0.0-probe --notes "probe `x` text" }
Write-Output "a`tb"
echo plain
~~~

첫 호출은 셸이 실행되기 전에 차단돼야 한다. 메시지 어느 위치에든 **[backtick-check-hook]**이 포함됐는지, 보고된 위치가 1:61과 1:63인지 확인한다. 거짓 분기이므로 릴리스 명령은 실행되지 않는다. 나머지 두 호출은 종료 0으로 끝나며, 각각 a와 b 사이의 탭 하나와 `plain`을 출력해야 한다. 다른 훅이 먼저 막았다면 어느 훅의 결과인지 판별할 수 없다.

아래 Bash 확인 명령은 Claude의 Bash·Monitor 도구 또는 POSIX용 Codex·Antigravity의 등록에만 사용한다. 첫 호출은 같은 표지와 함께 차단돼야 한다. 나머지 두 줄은 글자를 그대로 출력해야 한다.

~~~bash
if false; then echo "probe `x` text"; fi
echo 'literal `x`'
echo plain
~~~

### 실제 호스트 측정

| 호스트 | 실행 중인 버전 | 모드 | OS | 실행 셸 | 날짜 / 커밋 | 결과 |
|---|---|---|---|---|---|---|
| Claude Code | — | — | — | — | — | 미시험 |
| Codex | — | — | — | — | — | 미시험 |
| Antigravity | — | — | — | — | — | 미시험 |

이 표의 범위는 실제 호스트 대화에서 실행한 0.1.0이다. 로컬 어댑터 시험에는 합성 이벤트를 쓴다. Antigravity 훅 규약은 `decision`을 필수 필드로 명시한다. CLI 1.5.17의 검토·자동 모드에서는 빈 출력이 통과로 처리됐다. Antigravity 호스트 자체의 시간 초과 처리는 미측정이다. [Antigravity 훅](https://antigravity.google/docs/hooks.md)

## 남는 틈과 과잉 차단

- **Bash 문법.** 검사기는 Bash 인용 규칙을 근사하므로 드문 구문을 놓칠 수 있다. 작은따옴표, ANSI-C 인용 문자열, 구분자를 인용한 히어독, 주석, 역슬래시 하나로 이스케이프한 백틱은 일반적으로 글자를 보존한다. 기본 제공 훅은 달러-괄호 명령 치환을 허용한다. 검사기 CLI에서 `--strict`를 직접 지정해야 일부 혼합 문자열의 치환도 검사한다. 별도로 인용한 셸·SSH 인자 안의 스크립트, 글을 조용히 바꾸는 변수 치환은 검사 범위 밖이다.
- **Bash 해석의 한계.** 검사기는 원문과 역슬래시를 접은 형태를 함께 읽는다. Windows에서는 Git Bash가 캐리지 리턴(CR)을 버리는 동작도 반영한다. 인용 규칙이 다른 실행기에서는 불필요하게 막을 수 있다. 배열 첨자의 의미는 실행 시 변수의 종류에 따라 달라질 수 있다. 끝맺지 않은 히어독 뒤의 글은 해석이 모호할 수 있다. 깊이 150 또는 검사 예산 3초에 도달하면 그때까지의 결과로 판정한다. SessionStart는 시작·재개·clear·compact·fork 때 Bash와 Monitor를 확인한다. 훅 자체가 시작하지 않거나 점검 사이에 바뀌면 감지하지 못할 수 있다. SessionStart 경고는 하위 에이전트에게 보이지 않는다.
- **PowerShell 인식 범위.** 검사기는 gh release·pr·issue·api, git commit·tag·notes·merge에서 흔히 쓰는 글쓰기 형식을 인식한다. 앞선 호출에서 본문 파일에 쓴 글, 스크립트 파일 안의 명령, 스플래팅·변수로 구성한 인자, 동적 명령, Start-Process, 인코딩한 명령, 생성한 스크립트 블록은 놓칠 수 있다. gh repo edit --description, gh secret set --body, git stash -m, git commit-tree 등은 인식 범위 밖이다. 한 셸이 다른 셸을 띄우면 실제와 다른 셸의 규칙으로 검사할 수 있다. Codex의 `write_stdin` 입력은 PreToolUse를 거치지 않아 검사되지 않는다. 일부 특수 Codex 도구 경로도 PreToolUse를 건너뛸 수 있다. Antigravity는 도구 이름과 인자 이름을 대소문자까지 문자 그대로 비교한다. 인식하지 못하는 표기는 검사되지 않는다. 다른 종류의 셸로 전달한 입력은 다르게 해석될 수 있다. [Codex 훅 적용 범위](https://developers.openai.com/codex/hooks/)
- **PowerShell 문법과 상한.** 명령 낱말 사이의 주석, 식 바로 뒤 주석 안의 작은따옴표, 달러 기호 뒤의 블록 주석 시작, 괄호로 쓴 옵션 값, 생략하거나 줄을 나눈 -Command, 세 단계를 넘는 간접 평가는 인식하지 못할 수 있다. tag·merge의 붙여 쓴 메시지 옵션과 축약형도 놓칠 수 있다. Git 동사 앞 옵션은 32개까지 읽고, 일부 동사 뒤의 검색은 4,000자로 제한한다. 백틱과 인식된 게시 동작이 있는 명령이 400,000자를 넘거나 해석을 끝내지 못하면 차단할 수 있다.
- **호출 전체를 검사해서 생기는 차단.** 주석·인용 예시에 든 게시 동사, 다른 곳의 간접 평가, 파일로 커밋하는 명령과 무관한 이스케이프, --no-edit를 붙인 amend가 섞이면 막을 수 있다. 식에 붙은 주석과 PowerShell 구문 분석 중지 토큰 뒤의 글을 일반 인자로 읽을 수 있다. 읽기 전용 gh api 뒤의 -First·-Force·-Filter·-FilePath는 필드 쓰기로 인식할 수 있다. 읽기 전용 git tag·notes는 다른 문장의 낱말이나 스위치와 일치할 수 있다. 서로 다른 작업은 호출을 나누고, 게시 본문은 파일에 작성한 뒤 Git이나 GitHub CLI에 파일명을 넘긴다.
- **오류와 시간 초과.** 훅이 없거나 미신뢰 상태인 경우, 인터프리터가 없는 경우, 입력 형식이나 처리에 오류가 난 경우에는 검사 없이 진행될 수 있다. Codex는 호스트의 30초 제한이 지나면 호출을 진행할 수 있다. Claude Code도 PreToolUse의 15초 제한이 지나면 검사 없이 진행할 수 있다. Antigravity 어댑터는 검사기가 10초를 넘으면 빈 출력을 반환하므로 명령이 검사 없이 진행될 수 있다. Antigravity 호스트 선언의 제한은 15초다. Windows에서는 Git Bash 훅 래퍼가 시간 초과로 끝나도 자식 프로세스가 남을 수 있다. [Claude Code 훅 시간 제한](https://code.claude.com/docs/en/hooks)

### Python 버전과 로컬 실행 시간

**Python 3.11 이상이 필요한 이유.** Python 3.10은 정규식의 소유 한정자를 지원하지 않는다. 대체 패턴은 일반 한정자를 쓰므로 CRLF 줄 이음이 반복되면 PowerShell 검사 시간이 지수적으로 늘어날 수 있다. Python 3.10.11에서 줄 이음 20개는 3.3초, 22개는 12.3초가 걸렸다. 훅의 시간 제한에 걸리면 명령이 검사 없이 진행될 수 있다. Python 3.11 이상을 사용한다.

Windows 비교 측정은 2026-11-26(KST) 커밋 `bf18baf9`에서 Windows 11 Insider 빌드 26300.9974, Python 3.12.10, Git Bash 5.3.15, Windows PowerShell 5.1.26100.9818로 수행했다. 한 번 예열한 뒤 평문 이벤트 일곱 번의 중앙값은 Git Bash 사전 검사 189ms, cmd/PowerShell 596ms, cmd/Python 171ms였다. 각각 빈 바깥 셸의 시작 비용 중앙값을 빼면 약 15ms, 527ms, 103ms다. 이 합성 측정은 해당 커밋의 임시 사용자 설정에서 명령이 시작해 종료할 때까지의 시간이다. 0.1.0 실제 대화의 지연은 미측정이다. Claude 사전 검사는 백틱 표지가 없는 이벤트에서 Python을 띄우지 않는다. Windows Codex는 셸 호출마다 PowerShell을, Antigravity는 Python 어댑터를 띄운다.

## 제거·문제 해결·시험

설치한 호스트에 대해 `python -I -X utf8 -B install.py uninstall --host HOST`를 실행한다. 설치기는 설치 기록을 확인한 뒤 자신이 등록한 파일과 처리기를 제거한다. 패키지 폴더는 이미 사라지고 등록이 남아 있으면, 호스트 설정에서 오래된 훅을 확인해 제거한 뒤 다시 설치한다. Claude 훅의 문법 오류 때문에 셸 호출이 막히면 플러그인 화면이나 텍스트 편집기에서 등록을 해제하고 새 대화를 연다. 셸 문법 오류 자체가 종료 2를 반환하면 Claude가 이를 차단으로 해석할 수 있다. 따로 등록한 플러그인과 프로젝트 훅은 각각 별도의 등록을 가진다.

Windows에서는 `python -B tools/test_windows.py 65001`과 `python -B tools/test_windows.py 949`를 실행한다. 각 명령은 별도 콘솔을 열어 임시 홈에서 시험한다. Git Bash와 PowerShell 7을 설치하면 각각의 시험을 수행할 수 있다. Windows PowerShell 5.1은 별도로 확인한다. Bash 5.3 문법은 실제 Git Bash와 대조한다. `BACKTICK_TIMING_SCALE`은 절대 시간 기준(0.1·0.5·1.0·2.0초)에 곱하는 시험 변수다. 양의 유한한 수를 사용한다. 기본값은 1이고 CI에서는 3이다. 이 배율은 시험 기준에만 적용한다. 릴리스 노트와 커밋 메시지는 파일 편집기로 작성한 뒤 `--notes-file`, `--body-file` 또는 `git commit -F`로 넘긴다.
