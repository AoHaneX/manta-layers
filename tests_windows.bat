@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Installez les dependances avec installer_dependances.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 (
  echo Des tests ont echoue. Voir les erreurs ci-dessus.
  pause
  exit /b 1
)
echo Tests termines.
pause
exit /b 0
