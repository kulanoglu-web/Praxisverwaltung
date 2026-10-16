#define MyAppName "PraxisPro"
#ifndef MyAppVersion
  #define MyAppVersion "0.13.6"
#endif
#define MyAppPublisher "Erdogan Kulanoglu"
#define MyAppExeName "Praxisverwaltung.exe"

[Setup]
AppId={{B22B6B7B-5139-4A6D-9D71-0A2026092101}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PraxisPro
DefaultGroupName=PraxisPro
OutputDir=installer
OutputBaseFilename=PraxisPro_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=PraxisPro v{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
; Praxislogo im Setup: Programm-Symbol und Bilder der Installationsassistenten
SetupIconFile=assets\PraxisPro.ico
WizardImageFile=installer\wizard_164.bmp,installer\wizard_246.bmp,installer\wizard_328.bmp
WizardSmallImageFile=installer\wizard_small_55.bmp,installer\wizard_small_83.bmp,installer\wizard_small_110.bmp

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
; Einzeldatei-Build (PyInstaller --onefile) oder Ordner-Build werden beide erkannt.
#if FileExists("dist\Praxisverwaltung.exe")
Source: "dist\Praxisverwaltung.exe"; DestDir: "{app}"; Flags: ignoreversion
#else
Source: "dist\Praxisverwaltung\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{group}\PraxisPro"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\PraxisPro"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "PraxisPro starten"; Flags: nowait postinstall skipifsilent
