{ Included in [Code]. Gate automatic updates on explicit authorization AND the
  exit of the original process. No forced process termination is used. }
#ifndef UpdateRestartExecutable
  #define UpdateRestartExecutable "{app}\SacrificialTower.exe"
#endif
#ifndef UpdateRestartParameters
  #define UpdateRestartParameters ""
#endif
#ifndef UpdateRestartShowCommand
  #define UpdateRestartShowCommand 1
#endif
function UpdateOpenEvent(Access: LongWord; Inherit: Boolean; Name: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function UpdateSetEvent(Handle: THandle): Boolean;
  external 'SetEvent@kernel32.dll stdcall';
function UpdateWait(Handle: THandle; Milliseconds: LongWord): LongWord;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function UpdateOpenProcess(Access: LongWord; Inherit: Boolean; PID: LongWord): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function UpdateCloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

var
  UpdateReadyEvent, UpdateCommitEvent, UpdateCancelEvent, UpdateParent: THandle;
  UpdateStatusFile: String;
  UpdateHandoffActive, UpdateInstalled, UpdateFinished: Boolean;

procedure UpdateStage(const Stage: String);
begin
  Log('Sacrificial Tower update stage: ' + Stage);
  if UpdateStatusFile <> '' then
    if not SaveStringToFile(UpdateStatusFile, 'stage=' + Stage + #13#10, True) then
      Log('Update-Status konnte nicht geschrieben werden.');
end;

function ValidUpdateToken(const Token: String): Boolean;
var Index: Integer;
begin
  Result := False;
  if Length(Token) <> 32 then Exit;
  for Index := 1 to Length(Token) do
    if Pos(Token[Index], '0123456789abcdef') = 0 then Exit;
  Result := True;
end;

<event('InitializeSetup')>
function InitializeUpdateHandoff(): Boolean;
var
  Token, EventPrefix: String;
  ParentPID: Integer;
begin
  Result := True;
  Token := ExpandConstant('{param:STUPDATEHANDOFF|}');
  if Token = '' then Exit; { Older clients and manual installations remain supported. }
  Result := False;
  if not ValidUpdateToken(Token) then Exit;
  ParentPID := StrToIntDef(ExpandConstant('{param:STUPDATEPARENT|}'), 0);
  if ParentPID <= 0 then Exit;
  EventPrefix := 'Local\SacrificialTower-Update-' + Token + '-';
  UpdateReadyEvent := UpdateOpenEvent($0002, False, EventPrefix + 'ready');
  UpdateCommitEvent := UpdateOpenEvent($00100000, False, EventPrefix + 'commit');
  UpdateCancelEvent := UpdateOpenEvent($00100000, False, EventPrefix + 'cancel');
  UpdateParent := UpdateOpenProcess($00100000, False, ParentPID);
  if (UpdateReadyEvent = 0) or (UpdateCommitEvent = 0) or
     (UpdateCancelEvent = 0) or (UpdateParent = 0) then
  begin
    Log('Updateübergabe konnte nicht geöffnet werden; Installation gesperrt.');
    Exit;
  end;
  UpdateStatusFile := ExpandConstant('{param:STUPDATESTATUS|}');
  if (ExtractFileName(UpdateStatusFile) <> 'update-' + Token + '.status') or
     not SaveStringToFile(UpdateStatusFile, 'protocol=1' + #13#10 +
                         'attempt=' + Token + #13#10 + 'version={#AppVersion}' + #13#10, False) then
  begin
    Log('Update-Statusprotokoll konnte nicht angelegt werden.');
    UpdateStatusFile := '';
    Exit;
  end;
  UpdateHandoffActive := True;
  Result := True;
end;

<event('PrepareToInstall')>
function WaitForUpdateParent(var NeedsRestart: Boolean): String;
var
  Tick: Integer;
  Committed: Boolean;
begin
  Result := '';
  if not UpdateHandoffActive then Exit;
  UpdateStage('ready');
  if not UpdateSetEvent(UpdateReadyEvent) then
  begin
    Result := 'Die sichere Updateübergabe ist fehlgeschlagen.';
    Exit;
  end;
  Committed := False;
  for Tick := 1 to 2400 do { At most 120 seconds for safe application shutdown. }
  begin
    if UpdateWait(UpdateCancelEvent, 0) = 0 then
    begin
      UpdateStage('handoff_cancelled');
      Result := 'Die Updateübergabe wurde abgebrochen. Es wurden keine Programmdateien ersetzt.';
      Exit;
    end;
    if UpdateWait(UpdateCommitEvent, 0) = 0 then Committed := True;
    if UpdateWait(UpdateParent, 0) = 0 then
    begin
      if Committed then
      begin
        UpdateStage('parent_exited');
        Exit;
      end;
      UpdateStage('handoff_cancelled');
      Result := 'Das Programm wurde ohne bestätigte Updateübergabe beendet.';
      Exit;
    end;
    Sleep(50);
  end;
  UpdateStage('parent_exit_timeout');
  Result := 'Das Programm konnte nicht rechtzeitig sicher beendet werden. Installation gesperrt.';
end;

<event('CurStepChanged')>
procedure RecordUpdateInstallStep(CurStep: TSetupStep);
var ResultCode: Integer;
begin
  if not UpdateHandoffActive then Exit;
  if CurStep = ssInstall then UpdateStage('install_started');
  if CurStep = ssPostInstall then
  begin
    UpdateInstalled := True;
    UpdateStage('install_completed');
  end;
  if CurStep = ssDone then
  begin
    UpdateFinished := True;
    UpdateStage('setup_completed');
#ifndef UninstallIntegrationTest
    if Exec(ExpandConstant('{#UpdateRestartExecutable}'),
            ExpandConstant('{#UpdateRestartParameters}'), ExpandConstant('{app}'),
            {#UpdateRestartShowCommand}, ewNoWait, ResultCode) then
      UpdateStage('restart_started')
    else
    begin
      UpdateStage('restart_failed');
      Log('Programmneustart fehlgeschlagen: ' + IntToStr(ResultCode) + ' ' + SysErrorMessage(ResultCode));
    end;
#endif
  end;
end;

<event('DeinitializeSetup')>
procedure FinishUpdateHandoff();
begin
  if UpdateHandoffActive and not UpdateFinished then UpdateStage('setup_failed');
  if UpdateReadyEvent <> 0 then UpdateCloseHandle(UpdateReadyEvent);
  if UpdateCommitEvent <> 0 then UpdateCloseHandle(UpdateCommitEvent);
  if UpdateCancelEvent <> 0 then UpdateCloseHandle(UpdateCancelEvent);
  if UpdateParent <> 0 then UpdateCloseHandle(UpdateParent);
end;
