; Inno Setup 6 installer of Manta Layers, built by packaging\build.ps1 after PyInstaller:
;   ISCC.exe /DAppVersion=1.0.0 /Odist\release packaging\MantaLayers.iss
; Installs for the current user by default (no administrator rights); the user can
; choose an installation for all users. Uninstalling keeps the user's data:
; %LOCALAPPDATA%\MantaLayers (templates, fonts, models, logs, recovery) and the settings.

#ifndef AppVersion
  #error "Passer la version : ISCC /DAppVersion=x.y.z MantaLayers.iss"
#endif

#define AppName "Manta Layers"
#define AppExe "MantaLayers.exe"
#define SourceDir "..\dist\MantaLayers"

[Setup]
; Never change AppId: it identifies the installation for updates and uninstallation.
AppId={{A45B9C86-92FC-4E16-816E-068F492BA26A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Blue Shrimp
AppPublisherURL=https://github.com/AoHaneX/manta-layers
AppSupportURL=https://github.com/AoHaneX/manta-layers/issues
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=..\assets\manta.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputBaseFilename=MantaLayers-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An update replaces the libraries of the previous version instead of mixing them.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Same identity as main.py (SetCurrentProcessExplicitAppUserModelID): pinned icons group correctly.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "BlueShrimp.ReefKit.MantaLayers"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "BlueShrimp.ReefKit.MantaLayers"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
