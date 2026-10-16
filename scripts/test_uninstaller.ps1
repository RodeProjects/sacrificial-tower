[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$IsccPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [string]$WorkingRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..')
)
if ([string]::IsNullOrWhiteSpace($WorkingRoot)) {
    $WorkingRoot = Join-Path $projectRoot 'build\uninstall-integration'
}
$workingRootFull = [System.IO.Path]::GetFullPath($WorkingRoot)
$projectPrefix = $projectRoot.TrimEnd('\') + '\'
if (-not $workingRootFull.StartsWith(
    $projectPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Der Testordner muss innerhalb des Projektordners liegen: $workingRootFull"
}

$isccFull = (Resolve-Path -LiteralPath $IsccPath).Path
$scriptPath = Join-Path $projectRoot 'installer\SacrificialTower.iss'
$installRoot = Join-Path $workingRootFull 'program'
$userDataRoot = Join-Path $workingRootFull 'user-data'
$outputRoot = Join-Path $workingRootFull 'installer'
$installerBaseName = 'SacrificialTower-Uninstall-Test'
$installerPath = Join-Path $outputRoot ($installerBaseName + '.exe')
$testAppId = '{{' + [Guid]::NewGuid().ToString().ToUpperInvariant() + '}'

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Prozess fehlgeschlagen ($($process.ExitCode)): $FilePath"
    }
}

function Find-Uninstaller {
    $candidate = Get-ChildItem `
        -LiteralPath $installRoot `
        -Filter 'unins*.exe' `
        -File `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "Der Deinstaller wurde nicht angelegt: $installRoot"
    }
    return $candidate.FullName
}

function Get-TestUninstallEntries {
    $registryRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'
    if (-not (Test-Path -LiteralPath $registryRoot)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue |
        ForEach-Object {
            Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
        } |
        Where-Object {
            $locationProperty = $_.PSObject.Properties['InstallLocation']
            $null -ne $locationProperty -and
            -not [string]::IsNullOrWhiteSpace([string]$locationProperty.Value) -and
            [System.IO.Path]::GetFullPath([string]$locationProperty.Value).TrimEnd('\') -eq
                $installRoot.TrimEnd('\')
        }
    )
}

function Install-TestBuild {
    Invoke-CheckedProcess -FilePath $installerPath -ArgumentList @(
        '/SP-',
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/CURRENTUSER',
        '/NOICONS'
    )
    if (-not (Test-Path -LiteralPath (Join-Path $installRoot 'SacrificialTower.exe'))) {
        throw 'Die installierte Programmdatei fehlt.'
    }
    $entries = @(Get-TestUninstallEntries)
    if ($entries.Count -ne 1) {
        throw "Unerwartete Zahl registrierter Deinstaller: $($entries.Count)"
    }
    $displayVersion = $entries[0].PSObject.Properties['DisplayVersion'].Value
    if ([string]$displayVersion -ne $Version) {
        throw "Falsche registrierte Version: $displayVersion"
    }
}

function Uninstall-TestBuild {
    param([switch]$DeleteUserData)

    $arguments = @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART'
    )
    if ($DeleteUserData) {
        $arguments += '/DELETEUSERDATA'
    }
    Invoke-CheckedProcess -FilePath (Find-Uninstaller) -ArgumentList $arguments

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while (
        (Test-Path -LiteralPath (Join-Path $installRoot 'SacrificialTower.exe')) -and
        [DateTime]::UtcNow -lt $deadline
    ) {
        Start-Sleep -Milliseconds 100
    }
    if (Test-Path -LiteralPath (Join-Path $installRoot 'SacrificialTower.exe')) {
        throw 'Die Programmdateien wurden nicht vollständig entfernt.'
    }
    if (@(Get-TestUninstallEntries).Count -ne 0) {
        throw 'Der Windows-Deinstallationseintrag wurde nicht entfernt.'
    }
}

function Assert-RunningApplicationBlocksUninstall {
    $applicationPath = Join-Path $installRoot 'SacrificialTower.exe'
    $runtimeDataRoot = Join-Path $workingRootFull 'runtime-data'
    $previousAutoClose = $env:COOLING_TOWER_TEST_AUTOCLOSE_MS
    $previousDataRoot = $env:COOLING_TOWER_USER_DATA_ROOT
    $previousQtPlatform = $env:QT_QPA_PLATFORM
    $applicationProcess = $null
    try {
        $env:COOLING_TOWER_TEST_AUTOCLOSE_MS = '10000'
        $env:COOLING_TOWER_USER_DATA_ROOT = $runtimeDataRoot
        $env:QT_QPA_PLATFORM = 'offscreen'
        $applicationProcess = Start-Process `
            -FilePath $applicationPath `
            -PassThru `
            -WindowStyle Hidden
        Start-Sleep -Seconds 2
        if ($applicationProcess.HasExited) {
            throw "Die Testanwendung wurde vorzeitig beendet: $($applicationProcess.ExitCode)"
        }

        $blockedUninstall = Start-Process `
            -FilePath (Find-Uninstaller) `
            -ArgumentList @(
                '/VERYSILENT',
                '/SUPPRESSMSGBOXES',
                '/NORESTART'
            ) `
            -PassThru `
            -Wait `
            -WindowStyle Hidden
        if (-not (Test-Path -LiteralPath $applicationPath)) {
            throw (
                'Der Deinstaller hat trotz laufender Anwendung mit der ' +
                "Entfernung begonnen (Exitcode $($blockedUninstall.ExitCode))."
            )
        }
        if (@(Get-TestUninstallEntries).Count -ne 1) {
            throw 'Der Deinstallationseintrag wurde trotz laufender Anwendung entfernt.'
        }

        if (-not $applicationProcess.WaitForExit(15000)) {
            throw 'Die Testanwendung hat sich nicht kontrolliert beendet.'
        }
    }
    finally {
        if ($null -ne $applicationProcess -and -not $applicationProcess.HasExited) {
            Stop-Process -Id $applicationProcess.Id -Force -ErrorAction SilentlyContinue
            $applicationProcess.WaitForExit(5000) | Out-Null
        }
        $env:COOLING_TOWER_TEST_AUTOCLOSE_MS = $previousAutoClose
        $env:COOLING_TOWER_USER_DATA_ROOT = $previousDataRoot
        $env:QT_QPA_PLATFORM = $previousQtPlatform
    }
}

if (Test-Path -LiteralPath $workingRootFull) {
    Remove-Item -LiteralPath $workingRootFull -Recurse -Force
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

try {
    & $isccFull `
        '/Qp' `
        "/DAppVersion=$Version" `
        "/DAppPublisherName=$((Get-Content -LiteralPath (Join-Path $PSScriptRoot '../config/legal_profile.json') -Raw | ConvertFrom-Json).provider_name)" `
        "/DAppIdValue=$testAppId" `
        "/DDefaultInstallDir=$installRoot" `
        "/DStandaloneUserDataDir=$userDataRoot" `
        "/DInstallerOutputDir=$outputRoot" `
        "/DInstallerOutputBaseFilename=$installerBaseName" `
        '/DUninstallIntegrationTest=1' `
        $scriptPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $installerPath)) {
        throw 'Der isolierte Test-Installer konnte nicht gebaut werden.'
    }

    Install-TestBuild
    Assert-RunningApplicationBlocksUninstall
    New-Item -ItemType Directory -Path $userDataRoot -Force | Out-Null
    $preservedMarker = Join-Path $userDataRoot 'preserve-me.txt'
    Set-Content -LiteralPath $preservedMarker -Value 'persönliche Testdaten' -Encoding utf8
    Uninstall-TestBuild
    if (-not (Test-Path -LiteralPath $preservedMarker)) {
        throw 'Die stille Standard-Deinstallation hat persönliche Daten gelöscht.'
    }

    Install-TestBuild
    $manualProgramFile = Join-Path $installRoot 'manual-file.keep'
    Set-Content -LiteralPath $manualProgramFile -Value 'nicht vom Installer verwaltet' -Encoding utf8
    Uninstall-TestBuild -DeleteUserData
    if (Test-Path -LiteralPath $userDataRoot) {
        throw 'Die ausdrücklich angeforderte Datenlöschung war unvollständig.'
    }
    if (-not (Test-Path -LiteralPath $manualProgramFile)) {
        throw 'Eine fremde Datei im Programmordner wurde pauschal gelöscht.'
    }

    Write-Host 'Deinstaller-Integrationstest erfolgreich.'
}
finally {
    $remainingUninstaller = Get-ChildItem `
        -LiteralPath $installRoot `
        -Filter 'unins*.exe' `
        -File `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $remainingUninstaller) {
        try {
            Invoke-CheckedProcess `
                -FilePath $remainingUninstaller.FullName `
                -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
        }
        catch {
            Write-Warning "Test-Deinstaller konnte nicht nachbereinigt werden: $_"
        }
    }
    if (Test-Path -LiteralPath $workingRootFull) {
        Remove-Item -LiteralPath $workingRootFull -Recurse -Force
    }
}
