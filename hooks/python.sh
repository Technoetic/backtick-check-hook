# Called by the native package's Git Bash / POSIX shell hook.
run_python() {
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
            if [ "$name" = py.exe ]; then "$candidate" -3 "$@"; else "$candidate" "$@"; fi
            return $?
        done
    done
    return 127
}
