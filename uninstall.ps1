$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'plugins/codex-tps-inline/scripts/control.py') stop
& codex plugin remove 'codex-tps-inline@local-tps-inline'
if ($LASTEXITCODE -ne 0) { throw '插件移除失败。' }
& codex plugin marketplace remove 'local-tps-inline'
. (Join-Path $PSScriptRoot 'windows-shortcuts.ps1')
$runtimeDirectory = Join-Path $env:LOCALAPPDATA 'CodexTPSInline'
Restore-TpsCodexShortcuts -RuntimeDirectory $runtimeDirectory
foreach ($shortcutPath in @((Join-Path ([Environment]::GetFolderPath('Programs')) 'Codex TPS/Codex TPS.lnk'), (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Codex TPS.lnk'))) {
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
}
$manifestPath = Join-Path $runtimeDirectory 'codex-shortcuts.clixml'
$runtimeLauncher = Join-Path $runtimeDirectory 'launch.ps1'
if (-not (Test-Path -LiteralPath $manifestPath) -and (Test-Path -LiteralPath $runtimeLauncher)) { Remove-Item -LiteralPath $runtimeLauncher }
$legacyAutorun = Join-Path $runtimeDirectory 'autorun.ps1'
if (Test-Path -LiteralPath $legacyAutorun) { Remove-Item -LiteralPath $legacyAutorun -Force }
$legacyStartup = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Startup/Codex TPS AutoStart.lnk'
if (Test-Path -LiteralPath $legacyStartup) { Remove-Item -LiteralPath $legacyStartup -Force }
Write-Output 'TPS 插件和启动入口已移除；安装前的 Codex 快捷方式已恢复。'
