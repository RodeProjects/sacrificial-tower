#define AppVersion "9.9.9"
#define UpdateRestartExecutable "{cmd}"
#define UpdateRestartParameters '/D /C echo restarted>"{app}\restart-marker.txt"'
#define UpdateRestartShowCommand 0
[Setup]
AppName=Sacrificial Tower update handoff test
AppVersion={#AppVersion}
DefaultDirName={src}\unused
Uninstallable=no
PrivilegesRequired=lowest
DisableWelcomePage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
DisableProgramGroupPage=yes
CloseApplications=no
OutputBaseFilename=handoff-test
Compression=none
[Files]
Source: "update_payload.txt"; DestDir: "{app}"; Flags: ignoreversion
[Code]
#include "..\..\installer\UpdateHandoff.iss"
