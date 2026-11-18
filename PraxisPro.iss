#define MyAppName "PraxisPro"
#ifndef MyAppVersion
  #define MyAppVersion "0.21.0"
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

[Code]
// Deinstallation: Abfrage, ob die Praxisdaten erhalten bleiben oder vollständig gelöscht werden.
// Der Datenordner ist derselbe, den das Programm verwendet: %USERPROFILE%\Documents\Praxisverwaltung
// (bewusst nicht das Shell-Dokumente-Verzeichnis, weil es z. B. nach OneDrive umgeleitet sein kann).
// Stille Deinstallation (/SILENT, /VERYSILENT): Daten bleiben erhalten, außer mit /DELETEDATA=1.
var
  DeleteData: Boolean;

function PraxisDataDir: String;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\Documents\Praxisverwaltung';
end;

function PraxisProRunning: Boolean;
var
  Rc: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq Praxisverwaltung.exe" /NH | find /I "Praxisverwaltung.exe" >nul',
                 '', SW_HIDE, ewWaitUntilTerminated, Rc) and (Rc = 0);
end;

procedure ForceClosePraxisPro;
var
  Rc: Integer;
begin
  // /T beendet auch den eigentlichen Programmprozess (PyInstaller startet einen zweiten Prozess).
  Exec(ExpandConstant('{sys}') + '	askkill.exe', '/F /T /IM Praxisverwaltung.exe', '', SW_HIDE, ewWaitUntilTerminated, Rc);
  Sleep(2000);
end;

function InitializeUninstall: Boolean;
var
  Choice: Integer;
begin
  Result := True;
  DeleteData := False;
  // Laufendes PraxisPro hält die Programmdatei fest -> vorher schließen.
  if PraxisProRunning then
  begin
    if UninstallSilent then
      ForceClosePraxisPro
    else
      while PraxisProRunning do
      begin
        Choice := TaskDialogMsgBox('PraxisPro ist noch geöffnet',
          'Bitte PraxisPro schließen (vorher ungespeicherte Eingaben speichern) und dann „Erneut prüfen“ wählen.',
          mbError, MB_YESNOCANCEL, ['&Erneut prüfen', 'PraxisPro &beenden (ungespeicherte Eingaben gehen verloren)'], 0);
        if Choice = IDCANCEL then
        begin
          Result := False;
          exit;
        end;
        if Choice = IDNO then
          ForceClosePraxisPro;
      end;
  end;
  if UninstallSilent then
  begin
    DeleteData := ExpandConstant('{param:DELETEDATA|0}') = '1';
    exit;
  end;
  if not DirExists(PraxisDataDir) then
    exit;
  Choice := TaskDialogMsgBox('Was soll mit Ihren Praxisdaten geschehen?',
    'PraxisPro wird deinstalliert. Ihre Praxisdaten liegen in:' + #13#10 + PraxisDataDir + #13#10#13#10 +
    'Dazu gehören Klienten, Sitzungsnotizen, Rechnungen, Dokumente, Belege, der Datenschlüssel und Datensicherungen im Unterordner „Backups“.' + #13#10#13#10 +
    'Hinweis: Für Behandlungsdokumentation und Rechnungen gelten gesetzliche Aufbewahrungsfristen.',
    mbConfirmation, MB_YESNOCANCEL, ['&Praxisdaten behalten (empfohlen)'#13#10'Nur das Programm wird entfernt. Bei einer späteren Neuinstallation ist alles wieder da.',
     '&Alles löschen'#13#10'Programm UND alle Praxisdaten unwiderruflich löschen.'], 0);
  if Choice = IDCANCEL then
  begin
    Result := False;
    exit;
  end;
  if Choice = IDNO then
  begin
    if TaskDialogMsgBox('Wirklich ALLE Praxisdaten löschen?',
      'Alle Klienten, Notizen, Rechnungen, Dokumente, Belege, Datensicherungen im Ordner „Backups“ und der Datenschlüssel werden endgültig gelöscht.' + #13#10#13#10 +
      'Das kann NICHT rückgängig gemacht werden. Sicherungen auf einem USB-Stick oder an einem anderen Ort bleiben erhalten.',
      mbError, MB_YESNO, ['&Ja, alles endgültig löschen', '&Nein, Praxisdaten behalten'], IDNO) = IDYES then
      DeleteData := True;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Entschlüsselte Ansichtskopien immer entfernen (Datenschutz).
    DelTree(ExpandConstant('{%TEMP}') + '\PraxisPro_Ansicht', True, True, True);
    if DeleteData then
    begin
      if not DelTree(PraxisDataDir, True, True, True) then
        if not UninstallSilent then
          MsgBox('Einige Dateien konnten nicht gelöscht werden (evtl. noch geöffnet):' + #13#10 + PraxisDataDir, mbError, MB_OK);
    end
    else if (not UninstallSilent) and DirExists(PraxisDataDir) then
      MsgBox('PraxisPro wurde entfernt. Ihre Praxisdaten sind erhalten geblieben:' + #13#10 + PraxisDataDir, mbInformation, MB_OK);
  end;
end;
