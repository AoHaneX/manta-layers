<#
.SYNOPSIS
    Builds the Windows release of Manta Layers: portable ZIP and, when Inno Setup 6
    is installed, the installer. Everything is written under dist\ (ignored by Git).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipInstaller
#>
param(
    # Python used to create the build environment (64-bit, 3.11 or later; 3.13 is tested).
    [string]$Python = "py",
    [string[]]$PythonArguments = @("-3.13"),
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Version = [regex]::Match((Get-Content -Raw -Encoding UTF8 (Join-Path $Root "app\__init__.py")),
    '__version__\s*=\s*"([^"]+)"').Groups[1].Value
if (-not $Version) { throw "Version introuvable dans app\__init__.py" }

$BuildDir = Join-Path $Root "build"
$Venv = Join-Path $BuildDir "venv-release"
$DistDir = Join-Path $Root "dist"
$AppDir = Join-Path $DistDir "MantaLayers"
$ReleaseDir = Join-Path $DistDir "release"
$PortableZip = Join-Path $ReleaseDir "MantaLayers-$Version-Windows-Portable.zip"

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Echec ($LASTEXITCODE) : $Program $($Arguments -join ' ')" }
}

Write-Host "Manta Layers $Version : environnement de construction..."
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    Invoke-Checked $Python ($PythonArguments + @("-m", "venv", $Venv))
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
Invoke-Checked $VenvPython @("-m", "pip", "install", "--disable-pip-version-check", "--quiet",
    "-r", (Join-Path $PSScriptRoot "requirements-build.txt"))

Write-Host "PyInstaller..."
if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
Invoke-Checked $VenvPython @("-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", $DistDir, "--workpath", (Join-Path $BuildDir "pyinstaller"),
    (Join-Path $PSScriptRoot "MantaLayers.spec"))

# Licences next to the executable: MIT for the code, reserved rights for the artwork,
# and the notices of the bundled libraries when the file exists.
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $AppDir "LICENSE.txt")
$Notices = Join-Path $Root "THIRD_PARTY_NOTICES.md"
if (Test-Path $Notices) { Copy-Item $Notices (Join-Path $AppDir "THIRD_PARTY_NOTICES.md") }
else { Write-Warning "THIRD_PARTY_NOTICES.md absent : a ajouter avant toute publication." }

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
Get-ChildItem $ReleaseDir -Filter "MantaLayers-*" | Remove-Item -Force
Write-Host "Archive portable..."
# Python's zipfile writes "/" separators as the ZIP format requires; the .NET archive of
# Windows PowerShell 5.1 writes "\", which other systems extract as odd file names.
Invoke-Checked $VenvPython @("-c",
    "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', root_dir=sys.argv[2], base_dir='MantaLayers')",
    $PortableZip.Substring(0, $PortableZip.Length - 4), $DistDir)

if (-not $SkipInstaller) {
    $Candidates = @(
        (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | ForEach-Object Source),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }
    $Iscc = $Candidates | Select-Object -First 1
    if ($Iscc) {
        Write-Host "Installeur Inno Setup..."
        Invoke-Checked $Iscc @("/Q", "/DAppVersion=$Version", "/O$ReleaseDir",
            (Join-Path $PSScriptRoot "MantaLayers.iss"))
    } else {
        Write-Warning "Inno Setup 6 introuvable : installeur non construit (https://jrsoftware.org/isdl.php)."
    }
}

$Sums = Get-ChildItem $ReleaseDir -Filter "MantaLayers-$Version-*" | Sort-Object Name | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower(), $_.Name
}
$Sums | Set-Content -Encoding ASCII (Join-Path $ReleaseDir "SHA256SUMS.txt")
Write-Host "Termine :"
$Sums | ForEach-Object { Write-Host "  $_" }
