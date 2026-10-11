param([Parameter(Mandatory=$true)][string]$AppUserModelId, [string]$Arguments)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
internal class ActivationManager { }
[ComImport, Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IActivationManager {
    [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string appUserModelId, [MarshalAs(UnmanagedType.LPWStr)] string arguments, uint options, out uint processId);
    [PreserveSig] int ActivateForFile([MarshalAs(UnmanagedType.LPWStr)] string appUserModelId, IntPtr itemArray, [MarshalAs(UnmanagedType.LPWStr)] string verb, out uint processId);
    [PreserveSig] int ActivateForProtocol([MarshalAs(UnmanagedType.LPWStr)] string appUserModelId, IntPtr itemArray, out uint processId);
}
public static class CodexActivation {
    public static uint Launch(string id, string arguments) {
        var manager = (IActivationManager)new ActivationManager();
        uint pid;
        int hr = manager.ActivateApplication(id, arguments, 2, out pid);
        Marshal.ThrowExceptionForHR(hr);
        return pid;
    }
}
"@
    $activationProcessId = [CodexActivation]::Launch($AppUserModelId, $Arguments)
    @{pid=$activationProcessId} | ConvertTo-Json -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
