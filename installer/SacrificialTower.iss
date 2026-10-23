#ifndef AppVersion
  #error AppVersion muss aus src/cooling_tower/version.py übergeben werden.
#endif

#ifndef AppPublisherName
  #error AppPublisherName muss aus config/legal_profile.json übergeben werden.
#endif

#ifndef AppIdValue
  #define AppIdValue "{{D47169C5-9DE6-46AF-A8C9-72A394CD2949}"
#endif

#ifndef DefaultInstallDir
  #define DefaultInstallDir "{localappdata}\Programs\SacrificialTower"
#endif

#ifndef StandaloneUserDataDir
  #define StandaloneUserDataDir "{localappdata}\RodeProjects\SacrificialTower\standalone"
#endif

#ifndef InstallerOutputDir
  #define InstallerOutputDir "..\dist\installer"
#endif

#ifndef InstallerOutputBaseFilename
  #define InstallerOutputBaseFilename "SacrificialTowerSetup-" + AppVersion
#endif

#define ApplicationMutexName "SacrificialTower-Standalone-D47169C5-9DE6-46AF-A8C9-72A394CD2949"

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Messages]
SelectTasksDesc=
SelectTasksLabel2=Soll zusätzlich eine Desktop-Verknüpfung erstellt werden?

[Setup]
AppId={#AppIdValue}
AppName=Sacrificial Tower
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher={#AppPublisherName}
AppPublisherURL=https://github.com/RodeProjects
AppSupportURL=https://github.com/RodeProjects/sacrificial-tower/issues/new/choose
LicenseFile=..\dist\SacrificialTower\_internal\legal\published\terms.txt
DefaultDirName={#DefaultInstallDir}
AppendDefaultDirName=no
DefaultGroupName=Sacrificial Tower
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes
OutputDir={#InstallerOutputDir}
OutputBaseFilename={#InstallerOutputBaseFilename}
SetupLogging=yes
Uninstallable=yes
UninstallDisplayName=Sacrificial Tower
UninstallDisplayIcon={app}\SacrificialTower.exe
SetupIconFile=..\src\cooling_tower\gui\assets\app.ico
#ifdef SignBuild
SignTool=authenticode
SignedUninstaller=yes
#endif

[Files]
#ifdef SignBuild
Source: "..\dist\SacrificialTower\SacrificialTower.exe"; DestDir: "{app}"; Flags: ignoreversion signonce
#else
Source: "..\dist\SacrificialTower\SacrificialTower.exe"; DestDir: "{app}"; Flags: ignoreversion
#endif
Source: "..\dist\SacrificialTower\*"; Excludes: "SacrificialTower.exe"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Sacrificial Tower"; Filename: "{app}\SacrificialTower.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\Sacrificial Tower deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Sacrificial Tower"; Filename: "{app}\SacrificialTower.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; Flags: unchecked

#ifndef UninstallIntegrationTest
[Run]
Filename: "{app}\SacrificialTower.exe"; WorkingDir: "{app}"; Description: "Sacrificial-Tower jetzt starten?"; Flags: nowait postinstall skipifsilent
Filename: "{app}\SacrificialTower.exe"; WorkingDir: "{app}"; Flags: nowait skipifnotsilent; Check: IsAutomaticUpdate
#endif

[UninstallDelete]
; Nicht protokollierte Laufzeitdaten und danach leere Ordner behandelt der Code.
Type: dirifempty; Name: "{app}"

[Code]
#include "LicenseScroll.iss"
#include "UpdateHandoff.iss"

var
  DeleteStandaloneUserData: Boolean;
  ExistingReplacementPending: Boolean;
  ExistingUninstallerPath: String;
  ExistingReplacementDeletesUserData: Boolean;

<event('InitializeWizard')>
procedure InitializeTaskSelection;
begin
  if WizardSilent then
    Exit;
  WizardForm.SelectTasksLabel.AdjustHeight;
  WizardForm.TasksList.Top := WizardForm.SelectTasksLabel.Top +
    2 * WizardForm.SelectTasksLabel.Height;
  WizardForm.TasksList.Height := WizardForm.SelectTasksPage.ClientHeight -
    WizardForm.TasksList.Top;
end;

function InstalledApplicationRegistryKey(): String;
var
  RegistryId: String;
begin
  RegistryId := '{#AppIdValue}';
  if Copy(RegistryId, 1, 2) = '{{' then
    Delete(RegistryId, 1, 1);
  Result :=
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    RegistryId + '_is1';
end;

function ReadInstalledApplicationValue(
  const ValueName: String;
  var Value: String
): Boolean;
var
  RegistryKey: String;
begin
  RegistryKey := InstalledApplicationRegistryKey();
  Result := False;
  if IsWin64 then
    Result := RegQueryStringValue(HKCU64, RegistryKey, ValueName, Value);
  if not Result then
    Result := RegQueryStringValue(HKCU32, RegistryKey, ValueName, Value);
  if not Result then
    Result := RegQueryStringValue(HKCU, RegistryKey, ValueName, Value);
end;

function ExtractExecutableFromCommand(const CommandLine: String): String;
var
  ClosingQuote: Integer;
  ExecutableEnd: Integer;
  Remainder: String;
begin
  Result := '';
  if CommandLine = '' then
    Exit;

  if CommandLine[1] = '"' then
  begin
    Remainder := Copy(CommandLine, 2, Length(CommandLine) - 1);
    ClosingQuote := Pos('"', Remainder);
    if ClosingQuote > 0 then
      Result := Copy(Remainder, 1, ClosingQuote - 1);
    Exit;
  end;

  ExecutableEnd := Pos('.exe', Lowercase(CommandLine));
  if ExecutableEnd > 0 then
    Result := Copy(CommandLine, 1, ExecutableEnd + 3);
end;

function FindExistingApplication(
  var InstalledVersion: String;
  var UninstallerPath: String
): Boolean;
var
  InstallLocation: String;
  UninstallCommand: String;
begin
  Result :=
    ReadInstalledApplicationValue('DisplayVersion', InstalledVersion) and
    ReadInstalledApplicationValue('InstallLocation', InstallLocation) and
    ReadInstalledApplicationValue('UninstallString', UninstallCommand);
  if not Result then
    Exit;

  UninstallerPath := ExtractExecutableFromCommand(UninstallCommand);
  InstallLocation := RemoveBackslashUnlessRoot(InstallLocation);
  Result :=
    FileExists(UninstallerPath) and
    (CompareText(
      RemoveBackslashUnlessRoot(ExtractFileDir(UninstallerPath)),
      InstallLocation) = 0) and
    (Pos('unins', Lowercase(ExtractFileName(UninstallerPath))) = 1) and
    (CompareText(ExtractFileExt(UninstallerPath), '.exe') = 0);
end;

function HasCommandLineSwitch(const SwitchName: String): Boolean;
var
  Index: Integer;
  Expected: String;
begin
  Result := False;
  Expected := '/' + Uppercase(SwitchName);
  for Index := 1 to ParamCount do
  begin
    if Uppercase(ParamStr(Index)) = Expected then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsNonInteractiveUninstall(): Boolean;
begin
  Result :=
    HasCommandLineSwitch('SILENT') or
    HasCommandLineSwitch('VERYSILENT') or
    HasCommandLineSwitch('SUPPRESSMSGBOXES');
end;

function IsAutomaticUpdate(): Boolean;
begin
  Result := HasCommandLineSwitch('SACRIFICIALTOWERUPDATE') and not UpdateHandoffActive;
end;

function TestReplacementWasAccepted(): Boolean;
begin
  Result := False;
#ifdef UninstallIntegrationTest
  Result := HasCommandLineSwitch('TESTACCEPTREPLACEMENT');
#endif
end;

function TestUserDataShouldBeDeleted(): Boolean;
begin
  Result := False;
#ifdef UninstallIntegrationTest
  Result := HasCommandLineSwitch('TESTDELETEUSERDATA');
#endif
end;

function ConfirmReplacement(
  const InstalledVersion: String;
  const Comparison: Integer
): Boolean;
var
  MessageText: String;
begin
  if TestReplacementWasAccepted() then
  begin
    Result := True;
    Exit;
  end;

  if WizardSilent then
  begin
    Log(
      'Installation abgebrochen: Eine gleiche oder neuere Version darf nicht ' +
      'ohne ausdrückliche Bestätigung ersetzt werden.');
    Result := False;
    Exit;
  end;

  if Comparison = 0 then
    MessageText :=
      'Auf diesem Computer ist Sacrificial Tower Version ' +
      InstalledVersion + ' bereits installiert.' #13#10#13#10 +
      'Um dieselbe Version erneut vollständig einzurichten, werden zunächst ' +
      'die vorhandenen Programmdateien deinstalliert und anschließend neu ' +
      'installiert. Ihre persönlichen Daten bleiben dabei erhalten.' + #13#10#13#10 +
      'Möchten Sie die Neuinstallation fortsetzen?'
  else
    MessageText :=
      'Auf diesem Computer ist Sacrificial Tower Version ' +
      InstalledVersion + ' installiert. Der ausgewählte Installer enthält ' +
      'die ältere Version {#AppVersion}.' #13#10#13#10 +
      'Damit nach der Installation ausschließlich die zu Version ' +
      '{#AppVersion} gehörenden Programmdateien vorhanden sind, muss die ' +
      'derzeit installierte Version zuerst deinstalliert werden.' + #13#10#13#10 +
      'Möchten Sie fortfahren?';

  Result :=
    SuppressibleMsgBox(
      MessageText,
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2,
      IDNO) = IDYES;
end;

function SelectReplacementUserDataPolicy(): Integer;
begin
  if TestReplacementWasAccepted() then
  begin
    if TestUserDataShouldBeDeleted() then
      Result := IDYES
    else
      Result := IDNO;
    Exit;
  end;

  Result := SuppressibleMsgBox(
    'Sollen zusätzlich die persönlichen Daten der derzeit installierten ' +
    'Version unwiderruflich gelöscht werden?' #13#10#13#10 +
    'Dazu gehören Einstellungen, Profilzuordnungen, Logs und ' +
    'Standardausgaben.' #13#10#13#10 +
    'Das Beibehalten wird empfohlen. Falls die ältere Programmversion das ' +
    'vorhandene Einstellungsformat nicht vollständig unterstützt, schützt ' +
    'sie die bisherigen Einstellungen. Gemeinsam unterstützte, gültige ' +
    'Änderungen können bei einer späteren Aktualisierung wieder übernommen ' +
    'werden.' #13#10#13#10 +
    'Ja löscht die persönlichen Daten unwiderruflich. Nein behält sie bei. ' +
    'Abbrechen beendet die Installation ohne Änderungen.',
    mbConfirmation,
    MB_YESNOCANCEL or MB_DEFBUTTON2,
    IDNO);
end;

function RunExistingUninstaller(
  const UninstallerPath: String;
  const DeleteUserData: Boolean
): Boolean;
var
  Parameters: String;
  ResultCode: Integer;
begin
  Parameters := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART';
  if DeleteUserData then
    Parameters := Parameters + ' /DELETEUSERDATA';

  Log('Deinstalliere die vorhandene Version über: ' + UninstallerPath);
  Result := Exec(
    UninstallerPath,
    Parameters,
    ExtractFileDir(UninstallerPath),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode);
  if not Result then
  begin
    Log(
      'Vorherige Deinstallation konnte nicht gestartet werden: ' +
      SysErrorMessage(ResultCode));
    Exit;
  end;

  Result := ResultCode = 0;
  if not Result then
    Log(
      'Vorherige Deinstallation ist mit Rückgabecode ' +
      IntToStr(ResultCode) + ' fehlgeschlagen.');
end;

function InitializeSetup(): Boolean;
var
  InstalledVersion: String;
  UninstallerPath: String;
  InstalledPackedVersion: Int64;
  TargetPackedVersion: Int64;
  Comparison: Integer;
  UserDataChoice: Integer;
  DeleteUserData: Boolean;
begin
  Result := True;
  if not FindExistingApplication(InstalledVersion, UninstallerPath) then
    Exit;

  if not StrToVersion(InstalledVersion, InstalledPackedVersion) or
     not StrToVersion('{#AppVersion}', TargetPackedVersion) then
  begin
    Log('Installierte oder ausgewählte Version konnte nicht verglichen werden.');
    if not WizardSilent then
      SuppressibleMsgBox(
        'Die Version der vorhandenen Sacrificial-Tower-Installation konnte ' +
        'nicht sicher bestimmt werden. Bitte deinstallieren Sie die vorhandene ' +
        'Installation zunächst über die Windows-Einstellungen.',
        mbError,
        MB_OK,
        IDOK);
    Result := False;
    Exit;
  end;

  Comparison := ComparePackedVersion(TargetPackedVersion, InstalledPackedVersion);
  if Comparison > 0 then
  begin
    Log(
      'Reguläre Aktualisierung von Version ' + InstalledVersion +
      ' auf Version {#AppVersion}.');
    Exit;
  end;

  if not ConfirmReplacement(InstalledVersion, Comparison) then
  begin
    Log('Neuinstallation oder Downgrade wurde nicht bestätigt.');
    Result := False;
    Exit;
  end;

  DeleteUserData := False;
  if Comparison < 0 then
  begin
    UserDataChoice := SelectReplacementUserDataPolicy();
    if UserDataChoice = IDCANCEL then
    begin
      Log('Downgrade wurde bei der Auswahl der persönlichen Daten abgebrochen.');
      Result := False;
      Exit;
    end;
    DeleteUserData := UserDataChoice = IDYES;
  end;

  { Erst unmittelbar vor der eigentlichen Installation deinstallieren. So }
  { bleibt die vorhandene Version erhalten, falls der Assistent abgebrochen wird. }
  ExistingReplacementPending := True;
  ExistingUninstallerPath := UninstallerPath;
  ExistingReplacementDeletesUserData := DeleteUserData;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not ExistingReplacementPending then
    Exit;

  if CheckForMutexes('{#ApplicationMutexName}') then
  begin
    Log('Ersetzung abgebrochen: Sacrificial Tower wird noch ausgeführt.');
    Result :=
      'Sacrificial Tower wird noch ausgeführt.' #13#10#13#10 +
      'Bitte schließen Sie das Programm vollständig und versuchen Sie es erneut.';
    Exit;
  end;

  if not RunExistingUninstaller(
    ExistingUninstallerPath,
    ExistingReplacementDeletesUserData) then
  begin
    Result :=
      'Die vorhandene Sacrificial-Tower-Installation konnte nicht vollständig ' +
      'deinstalliert werden. Die ausgewählte Version wurde deshalb nicht ' +
      'installiert.';
    Exit;
  end;

  ExistingReplacementPending := False;
end;

function InitializeUninstall(): Boolean;
begin
  Result := not CheckForMutexes('{#ApplicationMutexName}');
  if Result then
    Exit;

  Log('Deinstallation abgebrochen: Sacrificial Tower wird noch ausgeführt.');
  if not IsNonInteractiveUninstall() then
  begin
    SuppressibleMsgBox(
      'Sacrificial Tower wird noch ausgeführt.' #13#10#13#10 +
      'Bitte schließen Sie das Programm vollständig und starten Sie die ' +
      'Deinstallation anschließend erneut.',
      mbError,
      MB_OK,
      IDOK);
  end;
end;

function StandaloneUserDataRoot(): String;
begin
  Result := RemoveBackslashUnlessRoot(ExpandConstant('{#StandaloneUserDataDir}'));
end;

procedure SelectUserDataPolicy();
var
  UserDataRoot: String;
begin
  DeleteStandaloneUserData := HasCommandLineSwitch('DELETEUSERDATA');
  if DeleteStandaloneUserData then
  begin
    Log('Explizite Löschung der persönlichen Standalone-Daten wurde angefordert.');
    Exit;
  end;

  if IsNonInteractiveUninstall() then
  begin
    Log('Stille Deinstallation: Persönliche Daten bleiben erhalten.');
    Exit;
  end;

  UserDataRoot := StandaloneUserDataRoot();
  DeleteStandaloneUserData :=
    SuppressibleMsgBox(
      'Sollen auch die persönlichen Daten dieser Installation unwiderruflich ' +
      'gelöscht werden?' #13#10#13#10 +
      'Dazu gehören Einstellungen, Profilzuordnungen, Logs und Standardausgaben ' +
      'unter:' #13#10 + UserDataRoot + #13#10#13#10 +
      'Auch ältere Einstellungen und Ausgaben in den Unterordnern config und ' +
      'output des Programmordners sowie unter _internal werden gelöscht.' #13#10#13#10 +
      'Wählen Sie Nein, um die Daten für eine spätere Neuinstallation zu behalten.',
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2,
      IDNO) = IDYES;
end;

function CleanupGetFileAttributes(const Path: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function HasReparsePointParent(const Path: String): Boolean;
var
  Parent, NextParent: String;
  Attributes: LongWord;
begin
  Result := False;
  Parent := ExtractFileDir(Path);
  while Parent <> '' do
  begin
    Attributes := CleanupGetFileAttributes(Parent);
    if Attributes <> $FFFFFFFF then
      if (Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then
      begin
        Result := True;
        Exit;
      end;
    NextParent := ExtractFileDir(Parent);
    if CompareText(Parent, NextParent) = 0 then
      Exit;
    Parent := NextParent;
  end;
end;

procedure DeleteUserDataDirectory(const Path: String; var FailedPaths: String);
begin
  { DelTree selbst folgt keinen Reparse Points; auch übergeordnete Junctions
    dürfen die Löschung nicht in ein fremdes Verzeichnis umlenken. Vor DirExists
    prüfen: Windows kann den Zugriff durch eine Junction bereits verweigern. }
  if not HasReparsePointParent(Path) then
  begin
    if not DirExists(Path) then
      Exit;
    Log('Lösche persönliche Daten: ' + Path);
    if DelTree(Path, True, True, True) and not DirExists(Path) then
      Exit;
  end;
  Log('WARNUNG: Persönliche Daten konnten nicht vollständig gelöscht werden: ' + Path);
  FailedPaths := FailedPaths + #13#10 + Path;
end;

procedure DeleteSelectedUserData();
var
  FailedPaths: String;
begin
  if not DeleteStandaloneUserData then
    Exit;

  FailedPaths := '';
  DeleteUserDataDirectory(StandaloneUserDataRoot(), FailedPaths);
  DeleteUserDataDirectory(ExpandConstant('{app}\config'), FailedPaths);
  DeleteUserDataDirectory(ExpandConstant('{app}\output'), FailedPaths);
  DeleteUserDataDirectory(ExpandConstant('{app}\_internal\config'), FailedPaths);
  DeleteUserDataDirectory(ExpandConstant('{app}\_internal\output'), FailedPaths);
  if FailedPaths = '' then
    Log('Persönliche Standalone-Daten einschließlich älterer Speicherorte wurden vollständig gelöscht.')
  else if not IsNonInteractiveUninstall() then
  begin
    SuppressibleMsgBox(
      'Ein Teil der persönlichen Daten konnte nicht gelöscht werden.' #13#10#13#10 +
      'Bitte schließen Sie Programme, die Dateien in diesem Ordner verwenden, ' +
      'und prüfen Sie die verbleibenden Ordner. Verknüpfte übergeordnete Ordner ' +
      'werden aus Sicherheitsgründen nicht durchsucht:' #13#10 + FailedPaths,
      mbError,
      MB_OK,
      IDOK);
  end;
end;

procedure RemoveEmptyProgramDirectories(const Path: String);
var
  FindRec: TFindRec;
  Attributes: LongWord;
begin
  Attributes := CleanupGetFileAttributes(Path);
  if Attributes = $FFFFFFFF then
    Exit;
  if (Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then
    Exit;
  if HasReparsePointParent(Path) then
    Exit;

  if FindFirst(AddBackslash(Path) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') and
           ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           ((FindRec.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) = 0) then
          RemoveEmptyProgramDirectories(AddBackslash(Path) + FindRec.Name);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  { Ausschließlich leere Verzeichnisse entfernen, niemals fremde Dateien. }
  if RemoveDir(Path) then
    Log('Leerer Programmordner entfernt: ' + Path);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    SelectUserDataPolicy()
  else if CurUninstallStep = usPostUninstall then
  begin
    DeleteSelectedUserData();
    RemoveEmptyProgramDirectories(ExpandConstant('{app}\config'));
    RemoveEmptyProgramDirectories(ExpandConstant('{app}\output'));
    RemoveEmptyProgramDirectories(ExpandConstant('{app}\_internal'));
    { Außerhalb der bekannten Programm-Unterordner nichts durchsuchen. }
    if RemoveDir(ExpandConstant('{app}')) then
      Log('Leerer Programmordner entfernt: ' + ExpandConstant('{app}'));
    Log('Sacrificial Tower: Deinstallationsbereinigung abgeschlossen.');
  end;
end;
