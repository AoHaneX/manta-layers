<#
.SYNOPSIS
    Builds the Windows release of Manta Layers: portable ZIP and Inno Setup installer, named after
    the ReefKit release convention read by ReefKit Launcher (packaging\reefkit_release.py).
    Everything is written under dist\ (ignored by Git):

        dist\release\MantaLayers-vX.Y.Z-win64.zip    MantaLayers.exe at the root of the archive
        dist\release\MantaLayers-vX.Y.Z-setup.exe
        dist\release\SHA256SUMS.txt
        dist\release\release-notes.md                 notes of the GitHub release (CHANGELOG.md section)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipInstaller
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Tag v1.1.0
#>
param(
    # Python used to create the build environment (64-bit, 3.11 or later; 3.13 is tested).
    [string]$Python = "py",
    [string[]]$PythonArguments = @("-3.13"),
    # Git tag being released (vX.Y.Z): the build stops if it differs from the version of the code.
    [string]$Tag = "",
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
$BaseName = "MantaLayers-v$Version"
$PortableZip = Join-Path $ReleaseDir "$BaseName-win64.zip"
$ReleaseTool = Join-Path $PSScriptRoot "reefkit_release.py"
$TagArguments = if ($Tag) { @("--tag", $Tag) } else { @() }

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Echec ($LASTEXITCODE) : $Program $($Arguments -join ' ')" }
}

function Find-InnoSetup {
    $Candidates = @(
        (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | ForEach-Object Source),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }
    $Iscc = $Candidates | Select-Object -First 1
    if (-not $Iscc) {
        throw "Inno Setup 6 introuvable (https://jrsoftware.org/isdl.php) : installez-le ou utilisez -SkipInstaller."
    }
    return $Iscc
}

Write-Host "Manta Layers $Version : environnement de construction..."
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    Invoke-Checked $Python ($PythonArguments + @("-m", "venv", $Venv))
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
# Fail early, before the long PyInstaller step, on a tag that differs from the version of the code.
Invoke-Checked $VenvPython (@($ReleaseTool, "version") + $TagArguments)
if (-not $SkipInstaller) { $Iscc = Find-InnoSetup }
Invoke-Checked $VenvPython @("-m", "pip", "install", "--disable-pip-version-check", "--quiet",
    "-r", (Join-Path $PSScriptRoot "requirements-build.txt"))

Write-Host "PyInstaller..."
if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
Invoke-Checked $VenvPython @("-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", $DistDir, "--workpath", (Join-Path $BuildDir "pyinstaller"),
    (Join-Path $PSScriptRoot "MantaLayers.spec"))

# Licences next to the executable: MIT for the code, reserved rights for the artwork,
# the notices of the bundled libraries and their full texts (exact bundled versions).
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $AppDir "LICENSE.txt")
Copy-Item (Join-Path $Root "THIRD_PARTY_NOTICES.md") (Join-Path $AppDir "THIRD_PARTY_NOTICES.md")
Invoke-Checked $VenvPython @((Join-Path $PSScriptRoot "collect_licenses.py"), (Join-Path $AppDir "licenses"))

# dist\release only holds the files of this build: SHA256SUMS.txt never describes a stale file.
New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
Get-ChildItem $ReleaseDir -File | Where-Object {
    $_.Name -like "MantaLayers-*" -or $_.Name -in @("SHA256SUMS.txt", "release-notes.md")
} | Remove-Item -Force
Write-Host "Archive portable..."
# MantaLayers.exe at the root of the archive, as the convention requires. Python's zipfile writes
# "/" separators as the ZIP format requires; the .NET archive of Windows PowerShell 5.1 writes "\".
Invoke-Checked $VenvPython @("-c",
    "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', root_dir=sys.argv[2])",
    $PortableZip.Substring(0, $PortableZip.Length - 4), $AppDir)

if (-not $SkipInstaller) {
    Write-Host "Installeur Inno Setup..."
    Invoke-Checked $Iscc @("/Q", "/DAppVersion=$Version", "/DOutputBaseName=$BaseName-setup", "/O$ReleaseDir",
        (Join-Path $PSScriptRoot "MantaLayers.iss"))
}

# Check the archive layout, then write SHA256SUMS.txt and release-notes.md.
$FinalizeArguments = @($ReleaseTool, "finalize", "--dir", $ReleaseDir) + $TagArguments
if ($SkipInstaller) { $FinalizeArguments += "--allow-missing-installer" }
Invoke-Checked $VenvPython $FinalizeArguments
# Start the application from the extracted archive, without Python on the PATH and with a
# temporary user profile, as ReefKit Launcher will: the user's own data is not touched.
Invoke-Checked $VenvPython @($ReleaseTool, "smoke", "--dir", $ReleaseDir)
Write-Host "Termine : $ReleaseDir"
