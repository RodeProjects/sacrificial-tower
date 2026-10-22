[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$IsccPath,
    [string]$WorkingRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($WorkingRoot)) {
    $WorkingRoot = Join-Path $projectRoot 'build\installer-license-test'
}
$testRoot = [System.IO.Path]::GetFullPath($WorkingRoot)
if (-not $testRoot.StartsWith($projectRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Der Testordner muss innerhalb des Repositorys liegen.'
}
$iscc = (Resolve-Path -LiteralPath $IsccPath).Path
# Keep each run isolated. These fixtures create no application directory, registry
# entries or uninstaller, and cancel before any installation in interactive mode.
$runRoot = Join-Path $testRoot ([Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$scriptTemplate = @'
[Setup]
AppName=License scroll integration test
AppVersion=1.0.0
DefaultDirName={tmp}\LicenseScrollTest
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
DisableWelcomePage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
DisableProgramGroupPage=yes
LicenseFile=__LICENSE__
OutputDir=__OUTPUT__
OutputBaseFilename=license-test
Compression=none
WizardStyle=modern

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Code]
#include "__INCLUDE__"
var
  TestTimer: UINT_PTR;
  TestStep: Integer;
  TestTicks: Integer;
  TestScrollWaitTicks: Integer;
  TestPageID: Integer;
  TestFinished: Boolean;

procedure TestPostQuitMessage(ExitCode: Integer);
  external 'PostQuitMessage@user32.dll stdcall';

procedure FinishTest(const Message: String);
begin
  if TestFinished then Exit;
  TestFinished := True;
  LicenseKillTimer(0, TestTimer);
  SaveStringToFile('__RESULT__', Message, False);
  { Inno's Close path ignores hidden, non-focusable wizard forms. This
    harmless fixture quits its message loop only after recording all assertions. }
  TestPostQuitMessage(0);
end;

procedure Require(Condition: Boolean; const Message: String);
begin
  if not Condition then
    RaiseException(Message);
end;

function ScrollState: String;
var
  Info: TLicenseScrollInfo;
begin
  Info.Size := 28;
  Info.Mask := 7;
  if LicenseGetScrollInfo(WizardForm.LicenseMemo.Handle, 1, Info) then
    Result := Format('range=%d..%d page=%d pos=%d end=%d', [
      Info.Minimum, Info.Maximum, Info.PageSize, Info.Position,
      Integer(LicenseTextEndVisible)])
  else
    Result := 'scroll info unavailable';
end;

procedure TestTick(Window: HWND; Message: UINT; ID: UINT_PTR; Time: DWORD);
begin
  Inc(TestTicks);
  try
    Require(TestTicks < 60, 'Test timed out');
    case TestStep of
      0: begin
        if WizardForm.CurPageID <> wpLicense then Exit;
        if __SHORT__ then
        begin
          Require(LicenseEndReached, 'Fully visible short text remained locked: ' + ScrollState);
          Require(WizardForm.NextButton.Enabled, 'Short license consent button disabled');
          Require(WizardForm.NextButton.Caption = 'Zustimmen und &weiter', 'Missing explicit consent caption');
          Require(not WizardForm.LicenseAcceptedRadio.Visible, 'Redundant acceptance radio visible');
          FinishTest('OK short');
          Exit;
        end;
        Require(not LicenseEndReached, 'Long license unlocked at start');
        Require(not WizardForm.LicenseAcceptedRadio.Visible, 'Redundant acceptance radio visible');
        Require(not WizardForm.LicenseNotAcceptedRadio.Visible, 'Redundant rejection radio visible');
        Require(not WizardForm.NextButton.Enabled, 'Next enabled before scrolling');
        Require(WizardForm.NextButton.Caption = 'Zustimmen und &weiter', 'Missing explicit consent caption');
        Require(WizardForm.BackButton.Left + WizardForm.BackButton.Width < WizardForm.NextButton.Left, 'Back overlaps consent');
        Require(WizardForm.NextButton.Left + WizardForm.NextButton.Width < WizardForm.CancelButton.Left, 'Consent overlaps cancel');
        { The navigation guard also rejects a forced button activation. }
        Require(not LicenseScrollNextButtonClick(wpLicense), 'Navigation guard allowed unread license');
        WizardForm.NextButton.Enabled := True;
        SendMessage(WizardForm.NextButton.Handle, $00F5, 0, 0);
        Require(WizardForm.CurPageID = wpLicense, 'Forced button activation bypassed navigation guard');
        Require(not WizardForm.NextButton.Enabled, 'Guard did not restore disabled state');
        SendMessage(WizardForm.LicenseMemo.Handle, $0115, 1, 0); { one line down }
        TestStep := 1;
      end;
      1: begin
        Require(not LicenseEndReached, 'Partial scrolling unlocked long license');
        Require(not WizardForm.NextButton.Enabled, 'Partial scrolling enabled Next');
        if __CARET__ then
        begin
          WizardForm.ActiveControl := WizardForm.LicenseMemo;
          SendMessage(WizardForm.LicenseMemo.Handle, $00B1,
            $7FFFFFFF, $7FFFFFFF);
          SendMessage(WizardForm.LicenseMemo.Handle, $00B7, 0, 0); { scroll caret into view }
        end
        else
          SendMessage(WizardForm.LicenseMemo.Handle, $0115, 7, 0); { bottom }
        TestStep := 2;
      end;
      2: begin
        { The two Windows timer callbacks are asynchronous. A visible bottom
          does not prove the separate 100ms production callback ran first. }
        if not LicenseEndReached then
        begin
          Inc(TestScrollWaitTicks);
          Require(TestScrollWaitTicks <= 20,
            'Scrollbar bottom did not unlock acceptance within five seconds: ' + ScrollState);
          Exit;
        end;
        Require(LicenseEndReached, 'Scrollbar bottom did not unlock acceptance: ' + ScrollState);
        Require(WizardForm.NextButton.Enabled, 'Consent button disabled at bottom');
        Require(WizardForm.CurPageID = wpLicense, 'Scrolling alone navigated without consent click');
        Require(LicenseScrollNextButtonClick(wpLicense), 'Navigation guard rejected completed scroll');
        SendMessage(WizardForm.LicenseMemo.Handle, $0115, 6, 0); { top }
        RefreshLicenseScroll;
        Require(WizardForm.NextButton.Enabled, 'Reading an earlier section reset consent');
        SendMessage(WizardForm.NextButton.Handle, $00F5, 0, 0);
        TestStep := 3;
      end;
      3: begin
        Require(WizardForm.CurPageID = TestPageID, 'Next did not navigate past license');
        Require(WizardForm.NextButton.Enabled, 'Scroll gate affected another page');
        Require(WizardForm.NextButton.Caption <> 'Zustimmen und &weiter', 'Consent caption leaked onto next page');
        Require(WizardForm.NextButton.Width = LicenseOriginalNextWidth, 'Normal button width not restored');
        SendMessage(WizardForm.BackButton.Handle, $00F5, 0, 0);
        Require(WizardForm.CurPageID = wpLicense, 'Back did not return to license');
        Require(WizardForm.NextButton.Enabled, 'Returning reset completed license review');
        Require(WizardForm.NextButton.Caption = 'Zustimmen und &weiter', 'Consent caption missing after return');
        FinishTest('OK __VARIANT__');
      end;
    end;
  except
    FinishTest('FAIL: ' + GetExceptionMessage);
  end;
end;

<event('InitializeWizard')>
procedure InitializeLicenseTest;
begin
  TestPageID := CreateCustomPage(wpLicense, 'Test page', 'No installation is performed').ID;
  if WizardSilent then
  begin
    Require(LicenseScrollNextButtonClick(wpLicense), 'Silent update blocked by scroll gate');
    SaveStringToFile('__RESULT__', 'OK silent', False);
  end
  else
    TestTimer := LicenseSetTimer(0, 0, 250, CreateCallback(@TestTick));
end;

<event('CancelButtonClick')>
procedure CancelLicenseTest(PageID: Integer; var Cancel, Confirm: Boolean);
begin
  Cancel := True;
  Confirm := False;
end;
'@

foreach ($variant in @('long', 'caret', 'actual', 'short', 'silent')) {
    $variantRoot = Join-Path $runRoot $variant
    New-Item -ItemType Directory -Path $variantRoot | Out-Null
    $licensePath = Join-Path $variantRoot 'license.txt'
    if ($variant -eq 'short') {
        $licenseText = 'Short license: the entire text fits in the visible area.'
    }
    elseif ($variant -eq 'actual') {
        $licenseText = Get-Content -LiteralPath (Join-Path $projectRoot 'dist\SacrificialTower\_internal\legal\published\terms.txt') -Raw
    }
    else {
        $licenseText = ((1..300 | ForEach-Object { "License paragraph $_. Please review the complete document." }) -join "`r`n")
    }
    [IO.File]::WriteAllText($licensePath, $licenseText, [Text.UTF8Encoding]::new($true))
    $resultPath = Join-Path $variantRoot 'result.txt'
    $fixture = $scriptTemplate.Replace('__LICENSE__', $licensePath).
        Replace('__OUTPUT__', $variantRoot).
        Replace('__INCLUDE__', (Join-Path $projectRoot 'installer\LicenseScroll.iss')).
        Replace('__RESULT__', $resultPath.Replace("'", "''")).
        Replace('__SHORT__', $(if ($variant -eq 'short') { 'True' } else { 'False' })).
        Replace('__CARET__', $(if ($variant -eq 'caret') { 'True' } else { 'False' })).
        Replace('__VARIANT__', $variant)
    $fixturePath = Join-Path $variantRoot 'test.iss'
    [IO.File]::WriteAllText($fixturePath, $fixture, [Text.UTF8Encoding]::new($true))
    & $iscc '/Q' $fixturePath
    if ($LASTEXITCODE -ne 0) { throw "Test-Installer konnte nicht gebaut werden: $variant" }
    $arguments = @('/SP-', '/NORESTART', '/SUPPRESSMSGBOXES')
    if ($variant -eq 'silent') { $arguments += '/VERYSILENT' }
    $process = Start-Process -FilePath (Join-Path $variantRoot 'license-test.exe') `
        -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(30000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Installer-Lizenztest hängt: $variant"
    }
    if (-not (Test-Path -LiteralPath $resultPath)) { throw "Kein Testergebnis: $variant" }
    $result = (Get-Content -LiteralPath $resultPath -Raw).Trim()
    if ($result -ne "OK $variant") { throw "Installer-Lizenztest fehlgeschlagen: $result" }
    Write-Host "Installer-Lizenztest erfolgreich: $variant"
}
