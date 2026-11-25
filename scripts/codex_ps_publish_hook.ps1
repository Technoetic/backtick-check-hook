# Windows PreToolUse adapter. The installed declaration can pin the interpreter.
param([string]$PythonPath, [switch]$PythonLauncher)

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$process = $null
try {
    $reader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8, $false)
    try {
        $payload = $reader.ReadToEnd().TrimStart([char]0xFEFF)
    } finally {
        $reader.Dispose()
    }
    if ($payload.IndexOf([char]96) -lt 0 -and -not $payload.Contains('\u0060')) { exit 0 }

    $event = ConvertFrom-Json -InputObject $payload
    if ($event.hook_event_name -cne 'PreToolUse' -or $event.tool_name -cne 'Bash') { exit 0 }
    $command = $event.tool_input.command
    if ($command -isnot [string] -or $command.IndexOf([char]96) -lt 0) { exit 0 }

    $start = [System.Diagnostics.ProcessStartInfo]::new()
    if ($PythonPath) {
        if (-not [IO.Path]::IsPathRooted($PythonPath)) { exit 0 }
    } else {
        foreach ($name in 'python.exe', 'py.exe') {
            $candidate = Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue |
                Where-Object { $_.Source -notlike '*\WindowsApps\*' } | Select-Object -First 1
            if ($candidate) {
                $PythonPath = $candidate.Source
                $PythonLauncher = $name -eq 'py.exe'
                break
            }
        }
        if (-not $PythonPath) { exit 0 }
    }
    $start.FileName = $PythonPath
    $guard = Join-Path $PSScriptRoot 'ps_publish_guard.py'
    $start.Arguments = '-I -X utf8 -B "' + $guard + '" --raw --block-code=42'
    if ($PythonLauncher) { $start.Arguments = '-3 ' + $start.Arguments }
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardError = $true
    $start.RedirectStandardOutput = $true
    $start.StandardErrorEncoding = $utf8

    $process = [System.Diagnostics.Process]::Start($start)
    $elapsed = [Diagnostics.Stopwatch]::StartNew()
    $reason = $process.StandardError.ReadToEndAsync()
    $output = $process.StandardOutput.ReadToEndAsync()
    $bytes = $utf8.GetBytes($command)
    $stream = $process.StandardInput.BaseStream
    $write = $stream.WriteAsync($bytes, 0, $bytes.Length)
    if (-not $write.Wait(10000)) {
        $process.Kill()
        exit 0
    }
    $process.StandardInput.BaseStream.Close()
    if (-not $process.WaitForExit([int][Math]::Max(0, 10000 - $elapsed.ElapsedMilliseconds))) {
        $process.Kill()
        exit 0
    }
    $reads = [Threading.Tasks.Task[]]@($reason, $output)
    if (-not [Threading.Tasks.Task]::WaitAll($reads, [int][Math]::Max(0, 10000 - $elapsed.ElapsedMilliseconds))) { exit 0 }
    if ($process.ExitCode -eq 42) {
        $decision = @{ hookSpecificOutput = @{
            hookEventName = 'PreToolUse'
            permissionDecision = 'deny'
            permissionDecisionReason = $reason.GetAwaiter().GetResult()
        } }
        $json = (ConvertTo-Json $decision -Depth 3 -Compress) + [Environment]::NewLine
        $response = $utf8.GetBytes($json)
        $stdout = [Console]::OpenStandardOutput()
        try {
            $stdout.Write($response, 0, $response.Length)
        } finally {
            $stdout.Dispose()
        }
    }
} catch {
    # The shared guard's contract allows on errors. Only exit code 42 denies.
} finally {
    if ($null -ne $process) { $process.Dispose() }
}
exit 0
