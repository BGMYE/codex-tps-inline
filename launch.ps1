param([string]$PythonExe = 'python', [string]$ControlScript = '', [string]$ThreadId = '', [string]$CodexHome = '')
$ErrorActionPreference = 'Stop'
$stateDirectory = Join-Path $env:LOCALAPPDATA 'CodexTPSInline'
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$logPath = Join-Path $stateDirectory 'launcher.log'
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $env:PYTHONUTF8 = '1'
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format o) + ' Launch; Python=' + $PythonExe)
    if (-not $ControlScript) { $ControlScript = Join-Path $PSScriptRoot 'plugins/codex-tps-inline/scripts/control.py' }
    $launchArguments = @($ControlScript, 'launch', '--direct-launch')
    if ($ThreadId) { $launchArguments += @('--thread', $ThreadId) }
    if ($CodexHome) { $env:CODEX_HOME = $CodexHome; $launchArguments += @('--home', $CodexHome) }
    $raw = & $PythonExe @launchArguments 2>&1
    $exitCode = $LASTEXITCODE
    $json = $raw -join "`n"
    $result = $json | ConvertFrom-Json
    Set-Content -LiteralPath (Join-Path $stateDirectory 'launch-result.json') -Value $json -Encoding UTF8
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format o) + ' Result=' + $result.stage)
    if ($exitCode -ne 0 -or $result.stage -eq 'error') { throw $result.message }
    if ($result.stage -ne 'connected') {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show($result.message, 'Codex TPS') | Out-Null
    }
} catch {
    $message = 'Codex TPS 启动失败：' + $_.Exception.Message + "`n诊断日志：" + $logPath
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format o) + ' Error=' + $_.Exception.Message)
    @{stage='error';message=$message} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $stateDirectory 'launch-result.json') -Encoding UTF8
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($message, 'Codex TPS') | Out-Null
    exit 1
}
