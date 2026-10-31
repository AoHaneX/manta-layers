@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [Manta Layers] Premier lancement : installation de Python et des bibliotheques si necessaire.
  call "%~dp0installer_dependances.bat"
  if errorlevel 1 goto error
)
"%~dp0.venv\Scripts\python.exe" -c "import PySide6; import PIL" >nul 2>nul
if errorlevel 1 (
  echo [Manta Layers] Des dependances sont manquantes, nouvelle tentative d'installation...
  call "%~dp0installer_dependances.bat"
  if errorlevel 1 goto error
)
echo [Manta Layers] Demarrage...
rem Run without a console: closing a console window would kill the application
rem without asking to save. "lancer_manta_layers.bat --console" keeps the messages visible.
if /i "%~1"=="--console" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
  if errorlevel 1 goto error
  exit /b 0
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
exit /b 0
:error
echo.
echo ERREUR : verifiez les messages affiches ci-dessus.
pause
exit /b 1
