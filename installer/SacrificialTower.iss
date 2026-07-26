#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{D47169C5-9DE6-46AF-A8C9-72A394CD2949}
AppName=Sacrificial Tower
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=RodeProjects
AppPublisherURL=https://github.com/RodeProjects
AppSupportURL=https://github.com/RodeProjects/sacrificial-tower
DefaultDirName={localappdata}\Programs\SacrificialTower
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
OutputDir=..\dist\installer
OutputBaseFilename=SacrificialTowerSetup-{#AppVersion}
SetupLogging=yes
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
Name: "{autodesktop}\Sacrificial Tower"; Filename: "{app}\SacrificialTower.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

[Run]
Filename: "{app}\SacrificialTower.exe"; WorkingDir: "{app}"; Description: "Sacrificial Tower starten"; Flags: nowait
