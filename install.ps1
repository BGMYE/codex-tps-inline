$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
& python -c "import sys; assert sys.version_info >= (3, 10), 'Requires Python 3.10+'"
if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.10+。' }
$pythonExe = (& python -c "import sys; print(sys.executable)").Trim()
$sourceControl = Join-Path $PSScriptRoot 'plugins/codex-tps-inline/scripts/control.py'
# A running Windows monitor holds its cache directory as the working directory.
& $pythonExe $sourceControl stop | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'TPS 旧监控停止失败。' }
& codex plugin marketplace add $PSScriptRoot --json
if ($LASTEXITCODE -ne 0) { throw '加入本地 marketplace 失败。' }
& codex plugin add 'codex-tps-inline@local-tps-inline' --json
if ($LASTEXITCODE -ne 0) {
    & $pythonExe $sourceControl start | Out-Null
    throw '插件安装失败。'
}
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$installedControl = Join-Path $codexHome 'plugins/cache/local-tps-inline/codex-tps-inline/0.4.0/scripts/control.py'
$runtimeDirectory = Join-Path $env:LOCALAPPDATA 'CodexTPSInline'
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$legacyAutorun = Join-Path $runtimeDirectory 'autorun.ps1'
if (Test-Path -LiteralPath $legacyAutorun) { Remove-Item -LiteralPath $legacyAutorun -Force }
$legacyStartup = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Startup/Codex TPS AutoStart.lnk'
if (Test-Path -LiteralPath $legacyStartup) { Remove-Item -LiteralPath $legacyStartup -Force }
$runtimeLauncher = Join-Path $runtimeDirectory 'launch.ps1'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launch.ps1') -Destination $runtimeLauncher -Force
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Codex TPS'
New-Item -ItemType Directory -Path $menu -Force | Out-Null
$shellObject = New-Object -ComObject WScript.Shell
$package = Get-AppxPackage -Name 'OpenAI.Codex' | Sort-Object Version -Descending | Select-Object -First 1
$launcherArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runtimeLauncher + '" -PythonExe "' + $pythonExe + '" -ControlScript "' + $installedControl + '" -CodexHome "' + $codexHome + '"'
$iconLocation = if ($package) { (Join-Path $package.InstallLocation 'app/ChatGPT.exe') + ',0' } else { '' }
. (Join-Path $PSScriptRoot 'windows-shortcuts.ps1')
foreach ($shortcutPath in @((Join-Path ([Environment]::GetFolderPath('Programs')) 'Codex.lnk'), (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Codex.lnk'))) {
    Set-TpsCodexShortcut -ShortcutPath $shortcutPath -RuntimeDirectory $runtimeDirectory -Arguments $launcherArguments -IconLocation $iconLocation
}
foreach ($shortcutPath in @((Join-Path $menu 'Codex TPS.lnk'), (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Codex TPS.lnk'))) {
    $shortcut = $shellObject.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $shortcut.Arguments = $launcherArguments
    $shortcut.WorkingDirectory = $runtimeDirectory
    $shortcut.Description = '打开常驻 TPS 的 Codex 窗口，所有对话自动显示'
    if ($package) { $shortcut.IconLocation = (Join-Path $package.InstallLocation 'app/ChatGPT.exe') + ',0' }
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}
# Wait for the old monitor to exit before loading the installed renderer script.
& $pythonExe $installedControl restart
if ($LASTEXITCODE -ne 0) { throw 'TPS 监控更新失败。' }
Write-Output '插件已安装。以后从桌面或开始菜单新建的 Codex 快捷方式打开，TPS 会一起启动，并记住上次开关状态。原 Microsoft Store 入口及已有任务栏固定图标不会被替换。'
