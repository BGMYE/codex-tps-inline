from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows shortcut integration")
class WindowsShortcutTests(unittest.TestCase):
    def test_install_update_restore_and_preserve_changed_shortcuts(self):
        source = Path(__file__).resolve().parents[1] / "windows-shortcuts.ps1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "check.ps1"
            script.write_text(r"""
param([string]$Source, [string]$TestRoot)
$ErrorActionPreference = 'Stop'
. $Source
$runtime = Join-Path $TestRoot 'runtime'
New-Item -ItemType Directory -Path $runtime | Out-Null
$link = Join-Path $TestRoot 'Codex.lnk'
$shellObject = New-Object -ComObject WScript.Shell

# A new shortcut starts the launcher and is removed on uninstall.
Set-TpsCodexShortcut $link $runtime '-File "launcher path.ps1" -CodexHome "custom home"'
$secondLink = Join-Path $TestRoot 'Menu Codex.lnk'
Set-TpsCodexShortcut $secondLink $runtime '-File "launcher path.ps1" -CodexHome "custom home"'
$shortcut = $shellObject.CreateShortcut($link)
if ($shortcut.Arguments -ne '-File "launcher path.ps1" -CodexHome "custom home"') { throw 'Arguments changed' }
if ($shortcut.WorkingDirectory -ne $runtime) { throw 'Working directory changed' }
Restore-TpsCodexShortcuts $runtime
if ((Test-Path -LiteralPath $link) -or (Test-Path -LiteralPath $secondLink)) { throw 'New shortcuts were not removed' }

# Original shortcut bytes survive repeated plugin installation and uninstall.
$original = $shellObject.CreateShortcut($link)
$original.TargetPath = Join-Path $env:SystemRoot 'System32/notepad.exe'
$original.Arguments = 'my original arguments'
$original.Save()
$originalHash = Get-TpsShortcutHash $link
Set-TpsCodexShortcut $link $runtime '-File "launcher.ps1" -ControlScript "version1.py"'
Set-TpsCodexShortcut $link $runtime '-File "launcher.ps1" -ControlScript "version2.py"'
$records = @(Import-Clixml -LiteralPath (Join-Path $runtime 'codex-shortcuts.clixml'))
if ($records.Count -ne 1 -or -not $records[0].backup) { throw 'Original backup was replaced during update' }
Restore-TpsCodexShortcuts $runtime
if ((Get-TpsShortcutHash $link) -ne $originalHash) { throw 'Original shortcut bytes were not restored' }

# A shortcut edited after installation and its original backup are preserved.
Set-TpsCodexShortcut $link $runtime '-File "launcher.ps1"'
$edited = $shellObject.CreateShortcut($link)
$edited.Arguments = 'user changed the shortcut'
$edited.Save()
$editedHash = Get-TpsShortcutHash $link
Restore-TpsCodexShortcuts $runtime
if ((Get-TpsShortcutHash $link) -ne $editedHash) { throw 'User-edited shortcut was changed' }
$retained = @(Import-Clixml -LiteralPath (Join-Path $runtime 'codex-shortcuts.clixml'))
if (-not (Test-Path -LiteralPath $retained[0].backup)) { throw 'Original backup was lost' }
Write-Output 'Shortcut lifecycle checks passed'
""", encoding="utf-8-sig")
            powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            result = subprocess.run([str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                     "-Source", str(source), "-TestRoot", str(root)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Shortcut lifecycle checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
