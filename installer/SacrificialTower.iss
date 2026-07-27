#ifndef AppVersion
  #define AppVersion "0.0.0"
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

[Setup]
AppId={#AppIdValue}
AppName=Sacrificial Tower
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=RodeProjects
AppPublisherURL=https://github.com/RodeProjects
AppSupportURL=https://github.com/RodeProjects/sacrificial-tower
DefaultDirName={#DefaultInstallDir}
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
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

#ifndef UninstallIntegrationTest
[Run]
Filename: "{app}\SacrificialTower.exe"; WorkingDir: "{app}"; Description: "Sacrificial Tower starten"; Flags: nowait
#endif

[UninstallDelete]
; Nur einen nach der protokollierten Deinstallation leeren Programmordner entfernen.
; Benutzerdaten werden ausschließlich durch den eng begrenzten Code unten behandelt.
Type: dirifempty; Name: "{app}"

[Code]
var
  DeleteStandaloneUserData: Boolean;

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
      'Daten anderer Sacrificial-Tower-Instanzen bleiben unangetastet.' #13#10#13#10 +
      'Wählen Sie Nein, um die Daten für eine spätere Neuinstallation zu behalten.',
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2,
      IDNO) = IDYES;
end;

procedure DeleteSelectedUserData();
var
  UserDataRoot: String;
begin
  if not DeleteStandaloneUserData then
    Exit;

  UserDataRoot := StandaloneUserDataRoot();
  if not DirExists(UserDataRoot) then
  begin
    Log('Keine persönlichen Standalone-Daten zum Löschen gefunden: ' + UserDataRoot);
    Exit;
  end;

  Log('Lösche persönliche Standalone-Daten: ' + UserDataRoot);
  if DelTree(UserDataRoot, True, True, True) and not DirExists(UserDataRoot) then
  begin
    Log('Persönliche Standalone-Daten wurden vollständig gelöscht.');
    Exit;
  end;

  Log('WARNUNG: Persönliche Standalone-Daten konnten nicht vollständig gelöscht werden.');
  if not IsNonInteractiveUninstall() then
  begin
    SuppressibleMsgBox(
      'Ein Teil der persönlichen Daten konnte nicht gelöscht werden.' #13#10#13#10 +
      'Bitte schließen Sie Programme, die Dateien in diesem Ordner verwenden, ' +
      'und entfernen Sie den verbleibenden Ordner bei Bedarf manuell:' #13#10 +
      UserDataRoot,
      mbError,
      MB_OK,
      IDOK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    SelectUserDataPolicy()
  else if CurUninstallStep = usPostUninstall then
    DeleteSelectedUserData();
end;
