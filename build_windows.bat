@echo off
REM Aurelia Finance Lab - Windows build (double-click or run from a Command Prompt in this folder).
REM All the work is done by build_windows.ps1; this wrapper only bypasses the PowerShell
REM execution policy for this one script. Extra arguments are passed through, e.g.
REM     build_windows.bat -Python C:\Python312\python.exe
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo Build failed with exit code %RC%. Read the messages above; logs are in the build folder.
) else (
  echo.
  echo Build finished. The application is in dist\Aurelia_Finance_Lab\Aurelia_Finance_Lab.exe
)
pause
exit /b %RC%
