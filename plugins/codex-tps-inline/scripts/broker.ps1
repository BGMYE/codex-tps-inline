param([string]$Executable, [string]$Arguments, [string]$WorkingDirectory)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    $desktopShell = New-Object -ComObject Shell.Application
    [int]$desktopWindowHandle = 0
    $desktop = $desktopShell.Windows().FindWindowSW(0, 0, 8, [ref]$desktopWindowHandle, 1)
    if (-not $desktop) { throw 'Windows desktop shell is unavailable.' }
    $desktop.Document.Application.ShellExecute($Executable, $Arguments, $WorkingDirectory, 'open', 0)
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
