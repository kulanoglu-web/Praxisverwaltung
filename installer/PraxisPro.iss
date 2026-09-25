#define MyAppName "PraxisPro"
#define MyAppVersion "0.12.1"
#define MyAppPublisher "Erdoğan Kulanoğlu"
#define MyAppExeName "PraxisPro.exe"
[Setup]
AppId={{C48A3215-B81A-4A8B-A1EF-7C74D57D1733}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PraxisPro
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\setup
OutputBaseFilename=PraxisPro_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "PraxisPro starten"; Flags: nowait postinstall skipifsilent
