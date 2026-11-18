@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0装备强化计算器.exe" (
  start "" "%~dp0装备强化计算器.exe"
  exit /b
)
if exist "%~dp0DicheGearAdvisor.exe" (
  start "" "%~dp0DicheGearAdvisor.exe"
  exit /b
)
if exist "%~dp0runtime\pythonw.exe" (
  set "TCL_LIBRARY=%~dp0runtime\tcl\tcl8.6"
  set "TK_LIBRARY=%~dp0runtime\tcl\tk8.6"
  start "" "%~dp0runtime\pythonw.exe" "%~dp0pc_app.py"
  exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 pc_app.py
  if errorlevel 1 pause
  exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
  python pc_app.py
  if errorlevel 1 pause
  exit /b
)
echo Python not found. Use the portable package, or install Python 3.12 from python.org.
pause
