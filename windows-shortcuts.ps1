function Get-TpsShortcutHash {
    param([string]$Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { [Convert]::ToBase64String($sha.ComputeHash([IO.File]::ReadAllBytes($Path))) }
    finally { $sha.Dispose() }
}

function Set-TpsCodexShortcut {
    param([string]$ShortcutPath, [string]$RuntimeDirectory, [string]$Arguments, [string]$IconLocation = '')
    $manifestPath = Join-Path $RuntimeDirectory 'codex-shortcuts.clixml'
    $records = @()
    if (Test-Path -LiteralPath $manifestPath) { $records = @(Import-Clixml -LiteralPath $manifestPath) }
    $record = $records | Where-Object { $_.path -eq $ShortcutPath } | Select-Object -First 1
    if ($record -and (Test-Path -LiteralPath $ShortcutPath) -and (Get-TpsShortcutHash $ShortcutPath) -ne $record.installedHash) {
        throw "Codex shortcut was changed after installation; preserved: $ShortcutPath"
    }
    if (-not $record) {
        $backup = $null
        if (Test-Path -LiteralPath $ShortcutPath) {
            $backupDirectory = Join-Path $RuntimeDirectory 'shortcut-backups'
            New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
            $backup = Join-Path $backupDirectory (([guid]::NewGuid().ToString()) + '.lnk')
            Copy-Item -LiteralPath $ShortcutPath -Destination $backup
        }
        $record = [pscustomobject]@{ path = $ShortcutPath; backup = $backup; installedHash = $null }
        $records += $record
    }
    $shellObject = New-Object -ComObject WScript.Shell
    $shortcut = $shellObject.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $RuntimeDirectory
    $shortcut.Description = 'Codex with automatic inline TPS; toggle in the toolbar'
    if ($IconLocation) { $shortcut.IconLocation = $IconLocation }
    $shortcut.WindowStyle = 7
    try {
        $shortcut.Save()
        $record.installedHash = Get-TpsShortcutHash $ShortcutPath
        $records | Export-Clixml -LiteralPath $manifestPath -Depth 4 -Force
    } catch {
        if ($record.backup) { Copy-Item -LiteralPath $record.backup -Destination $ShortcutPath -Force }
        elseif (Test-Path -LiteralPath $ShortcutPath) { Remove-Item -LiteralPath $ShortcutPath }
        throw
    }
}

function Restore-TpsCodexShortcuts {
    param([string]$RuntimeDirectory)
    $manifestPath = Join-Path $RuntimeDirectory 'codex-shortcuts.clixml'
    if (-not (Test-Path -LiteralPath $manifestPath)) { return }
    $remaining = @()
    foreach ($record in @(Import-Clixml -LiteralPath $manifestPath)) {
        $recordPath = if ($null -eq $record) { '' } else { [string]$record.path }
        if ([string]::IsNullOrWhiteSpace($recordPath)) { continue }
        if ((Test-Path -LiteralPath $recordPath) -and (Get-TpsShortcutHash $recordPath) -ne $record.installedHash) {
            Write-Warning "Changed Codex shortcut retained: $recordPath; original backup: $($record.backup)"
            $remaining += $record
            continue
        }
        $recordBackup = if ($null -eq $record) { '' } else { [string]$record.backup }
        if (-not [string]::IsNullOrWhiteSpace($recordBackup)) {
            Copy-Item -LiteralPath $recordBackup -Destination $recordPath -Force
            Remove-Item -LiteralPath $recordBackup
        } elseif (Test-Path -LiteralPath $recordPath) {
            Remove-Item -LiteralPath $recordPath
        }
    }
    if ($remaining.Count) {
        $remaining | Export-Clixml -LiteralPath $manifestPath -Depth 4 -Force
    } else {
        Remove-Item -LiteralPath $manifestPath
    }
}
