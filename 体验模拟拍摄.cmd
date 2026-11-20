@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import numpy, PIL.ImageTk, tkinter" >nul 2>nul
    if not errorlevel 1 (
        ".venv\Scripts\python.exe" app.py --demo
        goto :done
    )
)
if exist "D:\Anaconda3\python.exe" (
    "D:\Anaconda3\python.exe" app.py --demo
    goto :done
)
python app.py --demo
:done
if errorlevel 1 pause
