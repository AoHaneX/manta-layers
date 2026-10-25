@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Installez les dependances avec installer_dependances.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import pytest" >nul 2>nul
if errorlevel 1 (
  echo pytest absent : installation des outils de test...
  ".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
)
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 (
  echo Des tests ont echoue. Voir les erreurs ci-dessus.
  pause
  exit /b 1
)
echo Tests termines.
pause
exit /b 0
