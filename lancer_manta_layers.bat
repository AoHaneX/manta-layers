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
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
if errorlevel 1 goto error
exit /b 0
:error
echo.
echo ERREUR : verifiez les messages affiches ci-dessus.
pause
exit /b 1
