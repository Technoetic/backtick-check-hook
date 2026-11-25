# Bash is selected explicitly by the hook declaration, including under POSIX sh.
set +e
LC_ALL=C
python=()
case "$1" in
    --python) python=("$2"); shift 2 ;;
    --discover) shift ;;
    *) exit 1 ;;
esac
mode=$1
guard=$2

if [ "$mode" = check ]; then
    IFS= read -r -d '' data
    case "$data" in *'`'*|*u0060*) ;; *) exit 0 ;; esac
elif [ "$mode" != session ]; then
    exit 1
fi

find_python() {
    local name dir candidate
    local -a names directories
    case "$OSTYPE" in
        msys*|cygwin*|win32*) names=(python.exe py.exe) ;;
        *) names=(python3) ;;
    esac
    IFS=: read -r -a directories <<< "$PATH"
    for name in "${names[@]}"; do
        for dir in "${directories[@]}"; do
            case "$dir" in /*) ;; *) continue ;; esac
            case "$dir" in */[Ww]indows[Aa]pps*) continue ;; esac
            [ "$dir" -ef "$PWD" ] && continue
            case "$dir/" in "$PWD/"*) continue ;; esac
            candidate="$dir/$name"
            [ -f "$candidate" ] && [ -x "$candidate" ] || continue
            python=("$candidate")
            if [ "$name" = py.exe ]; then python+=(-3); fi
            return 0
        done
    done
    return 127
}

run_guard() {
    if [ "${#python[@]}" -eq 0 ]; then find_python || return 127; fi
    "${python[@]}" -I -X utf8 -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 78)' || return $?
    "${python[@]}" -I -X utf8 -B "$guard" "$@"
}

if [ "$mode" = check ]; then
    printf '%s' "$data" | run_guard --block-code=42
    [ $? -eq 42 ] && exit 2
    exit 0
fi

if [ "${#python[@]}" -gt 0 ]; then
    run_guard --self-test --installed
else
    run_guard --self-test
fi
rc=$?
if [ "$rc" -eq 78 ]; then
    echo '[backtick-check-hook] Python 3.11 or later is required to run the checks.'
fi
exit "$rc"
