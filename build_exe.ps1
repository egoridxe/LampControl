$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

& ".\.venv\Scripts\python.exe" "make_icon.py"

& ".\.venv\Scripts\pyinstaller.exe" `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "LampControl" `
    --icon "assets\lamp.ico" `
    --add-data "assets;assets" `
    --collect-data "customtkinter" `
    --collect-all "bleak" `
    --collect-all "winrt" `
    --collect-all "pyaudiowpatch" `
    "main.py"

Copy-Item -Force "dist\LampControl.exe" "LampControl.exe"
Remove-Item -Recurse -Force "build", "dist", "LampControl.spec" -ErrorAction SilentlyContinue
Write-Host "Built: $PSScriptRoot\LampControl.exe"
