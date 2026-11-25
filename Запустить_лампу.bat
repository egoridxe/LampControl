@echo off
cd /d "%~dp0"
if exist "LampControl.exe" (
    start "" "LampControl.exe"
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
) else (
    python "main.py"
)
