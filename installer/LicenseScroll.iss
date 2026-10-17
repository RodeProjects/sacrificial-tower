{ Included in [Code]. Require the end of the visible license before acceptance.
  Windows SCROLLINFO contains seven 32-bit fields on both x86 and x64. }
type
  TLicenseScrollInfo = record
    Size: UINT;
    Mask: UINT;
    Minimum: Integer;
    Maximum: Integer;
    PageSize: UINT;
    Position: Integer;
    TrackPosition: Integer;
  end;

function LicenseGetScrollInfo(Window: HWND; Bar: Integer;
  var Info: TLicenseScrollInfo): Boolean;
  external 'GetScrollInfo@user32.dll stdcall';
function LicenseSetTimer(Window: HWND; ID: UINT_PTR; Interval: UINT;
  Callback: UINT_PTR): UINT_PTR;
  external 'SetTimer@user32.dll stdcall';
function LicenseKillTimer(Window: HWND; ID: UINT_PTR): Boolean;
  external 'KillTimer@user32.dll stdcall';
function LicenseGetWindowStyle(Window: HWND; Index: Integer): LongWord;
  external 'GetWindowLongW@user32.dll stdcall';

var
  LicenseEndReached: Boolean;
  LicenseScrollTimer: UINT_PTR;
  LicenseScrollCallback: UINT_PTR;
  LicenseOriginalNextCaption: String;
  LicenseOriginalNextWidth: Integer;
  LicenseOriginalNextLeft: Integer;
  LicenseOriginalBackLeft: Integer;

procedure StopLicenseScrollTimer;
begin
  if LicenseScrollTimer <> 0 then
  begin
    LicenseKillTimer(0, LicenseScrollTimer);
    LicenseScrollTimer := 0;
  end;
end;

function LicenseTextEndVisible: Boolean;
var
  Info: TLicenseScrollInfo;
begin
  Info.Size := 28;
  Info.Mask := 7;  { SIF_RANGE, SIF_PAGE and SIF_POS }
  Result := False;
  if LicenseGetScrollInfo(WizardForm.LicenseMemo.Handle, 1, Info) then
    { RichEdit can round its bottom position one pixel below the standard
      inclusive scrollbar maximum. This still shows the full final line. }
    Result := (Info.PageSize > 0) and
      (Info.Position >= Info.Maximum - Integer(Info.PageSize))
  else
    { RichEdit removes the vertical scrollbar when the whole text fits. }
    Result := (LicenseGetWindowStyle(WizardForm.LicenseMemo.Handle, -16)
      and $00200000) = 0;
end;

procedure RefreshLicenseScroll;
begin
  if WizardSilent or (WizardForm.CurPageID <> wpLicense) then
    Exit;

  if not LicenseEndReached then
    LicenseEndReached := LicenseTextEndVisible;
  WizardForm.NextButton.Enabled := LicenseEndReached;
  if LicenseEndReached then
  begin
    WizardForm.PageDescriptionLabel.Caption :=
      'Mit „Zustimmen und weiter“ akzeptieren Sie die Bedingungen.';
    StopLicenseScrollTimer;
  end;
end;

procedure LicenseScrollTick(Window: HWND; Message: UINT; ID: UINT_PTR; Time: DWORD);
begin
  RefreshLicenseScroll;
end;

<event('InitializeWizard')>
procedure InitializeLicenseScroll;
begin
  if WizardSilent then
    Exit;
  LicenseEndReached := False;
  { The native wizard requires this internal radio state before it calls the
    navigation guard. Actual consent is the explicitly labelled button click. }
  WizardForm.LicenseAcceptedRadio.Checked := True;
  WizardForm.LicenseAcceptedRadio.Visible := False;
  WizardForm.LicenseNotAcceptedRadio.Visible := False;
  WizardForm.LicenseMemo.Height := WizardForm.LicenseNotAcceptedRadio.Top +
    WizardForm.LicenseNotAcceptedRadio.Height - WizardForm.LicenseMemo.Top;
  LicenseOriginalNextCaption := WizardForm.NextButton.Caption;
  LicenseOriginalNextWidth := WizardForm.NextButton.Width;
  LicenseOriginalNextLeft := WizardForm.NextButton.Left;
  LicenseOriginalBackLeft := WizardForm.BackButton.Left;
  LicenseScrollCallback := CreateCallback(@LicenseScrollTick);
end;

<event('CurPageChanged')>
procedure LicenseScrollPageChanged(PageID: Integer);
begin
  StopLicenseScrollTimer;
  if WizardSilent then
    Exit;
  if PageID <> wpLicense then
  begin
    WizardForm.NextButton.Width := LicenseOriginalNextWidth;
    WizardForm.NextButton.Left := LicenseOriginalNextLeft;
    WizardForm.BackButton.Left := LicenseOriginalBackLeft;
    if WizardForm.NextButton.Caption = 'Zustimmen und &weiter' then
      WizardForm.NextButton.Caption := LicenseOriginalNextCaption;
    Exit;
  end;
  WizardForm.NextButton.Caption := 'Zustimmen und &weiter';
  WizardForm.NextButton.Width := ScaleX(180);
  WizardForm.NextButton.Left := WizardForm.CancelButton.Left - ScaleX(8) -
    WizardForm.NextButton.Width;
  WizardForm.BackButton.Left := WizardForm.NextButton.Left - ScaleX(8) -
    WizardForm.BackButton.Width;
  WizardForm.PageDescriptionLabel.Caption :=
    'Bitte lesen Sie die Lizenzvereinbarung vollständig durch. Am Ende des Textes können Sie Ihre Zustimmung erteilen.';
  RefreshLicenseScroll;
  if not LicenseEndReached then
  begin
    { Poll the native scrollbar so mouse, keyboard and scrollbar dragging all work. }
    LicenseScrollTimer := LicenseSetTimer(0, 0, 100, LicenseScrollCallback);
    if LicenseScrollTimer = 0 then
      RaiseException('Die Prüfung der Lizenzanzeige konnte nicht gestartet werden.');
  end;
end;

<event('NextButtonClick')>
function LicenseScrollNextButtonClick(PageID: Integer): Boolean;
begin
  Result := True;
  if WizardSilent or (PageID <> wpLicense) then
    Exit;
  RefreshLicenseScroll;
  Result := LicenseEndReached;
end;

<event('DeinitializeSetup')>
procedure DeinitializeLicenseScroll;
begin
  StopLicenseScrollTimer;
end;
