@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 est introuvable. Installez Python 3.11 ou version plus recente depuis python.org.
    echo Cochez l'option Add Python to PATH puis recommencez.
    exit /b 1
  )
  set "PYTHON=python"
)
%PYTHON% -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 (
  echo Python 3.11 ou version plus recente est necessaire. Installez-le depuis python.org puis recommencez.
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creation de l'environnement virtuel...
  %PYTHON% -m venv ".venv"
  if errorlevel 1 exit /b 1
)
echo Installation des bibliotheques Python [connexion Internet necessaire uniquement ici]...
rem La mise a jour de pip est utile mais pas indispensable : un echec (proxy, hors ligne) ne bloque pas l'installation.
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 echo Mise a jour de pip impossible, installation poursuivie avec la version actuelle.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
echo Installation terminee.
exit /b 0
