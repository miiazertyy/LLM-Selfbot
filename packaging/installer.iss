; Inno Setup script, LLMSelfbotSetup.exe
; Usage (from repo root): iscc packaging\installer.iss

#define AppName "LLMSelfbot"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppPublisher "LLMSelfbot"

[Setup]
AppId={{8F6D9C2E-3B1A-4E7F-9C24-SELFBOT001}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\LLMSelfbot
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=LLMSelfbotSetup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\resources\icon.ico
UninstallDisplayIcon={app}\LLMSelfbot.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\LLMSelfbot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\LLMSelfbot.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\LLMSelfbot.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\LLMSelfbot.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

; Only what the installer put here. Config, memory, pictures and keys live in
; %APPDATA%\LLMSelfbot and deliberately survive an uninstall.
;
; This used to write a portable.txt marker after installing, which told the app
; to keep all of that inside its own install folder instead. The line below
; then deleted the lot on uninstall, and an update would have done the same.
[UninstallDelete]
Type: filesandordirs; Name: "{app}"
