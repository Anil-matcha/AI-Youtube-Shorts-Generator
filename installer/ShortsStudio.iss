; Inno Setup definition for the professional Windows installer.
; Build with: ISCC.exe installer\ShortsStudio.iss

#define MyAppName "Shorts Studio"
#define MyAppVersion "0.10.0"
#define MyAppPublisher "wiifhub"
#define MyAppURL "https://github.com/wiifhub/AI-Youtube-Shorts-Generator"
#define MyAppExeName "ShortsStudio.exe"

[Setup]
AppId={{F0A2B6F0-0A2E-4DB9-9B73-8A8FBE5BB8F4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\Shorts Studio
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=ShortsStudio-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\shorts_studio_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Windows installer
VersionInfoCopyright=Copyright (c) 2026 {#MyAppPublisher}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\ShortsStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\.env.example"; DestDir: "{app}"; DestName: ".env.example"; Flags: ignoreversion

[Icons]
Name: "{group}\Shorts Studio"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\assets\shorts_studio_icon.ico"; IconIndex: 0
Name: "{group}\Uninstall Shorts Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Shorts Studio"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\assets\shorts_studio_icon.ico"; IconIndex: 0; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Shorts Studio"; Flags: nowait postinstall skipifsilent
