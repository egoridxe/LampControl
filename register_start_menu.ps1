$ErrorActionPreference = "Stop"
$exePath = Join-Path $PSScriptRoot "LampControl.exe"

if (-not (Test-Path $exePath)) {
    throw "LampControl.exe not found at $exePath"
}

$startPrograms = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shortcutPath = Join-Path $startPrograms "Lamp Control.lnk"

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $exePath
$sc.WorkingDirectory = $PSScriptRoot
$sc.Description = "Управление Bluetooth LED лампой"
$sc.IconLocation = "$exePath,0"
$sc.Save()

# Notify Windows Shell so Start Menu ("Недавно добавленные") indexes the new shortcut immediately
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ShellRefresh {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(uint wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);
}
"@
[ShellRefresh]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)

Write-Host "Shortcut created: $shortcutPath -> $exePath"
