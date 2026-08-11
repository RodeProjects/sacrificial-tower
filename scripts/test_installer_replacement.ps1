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

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($WorkingRoot)) {
    $WorkingRoot = Join-Path $projectRoot 'build\installer-replacement-integration'
}
$workingRootFull = [System.IO.Path]::GetFullPath($WorkingRoot)
$projectPrefix = $projectRoot.TrimEnd('\') + '\'
if (-not $workingRootFull.StartsWith(
    $projectPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Der Testordner muss innerhalb des Projektordners liegen: $workingRootFull"
}

Import-Module (
    Join-Path $PSScriptRoot 'InstallerReplacementVersion.psm1'
) -Force
$olderVersion = Get-OlderInstallerTestVersion -Version $Version
$isccFull = (Resolve-Path -LiteralPath $IsccPath).Path
$scriptPath = Join-Path $projectRoot 'installer\SacrificialTower.iss'
$installRoot = Join-Path $workingRootFull 'program'
$userDataRoot = Join-Path $workingRootFull 'user-data'
$outputRoot = Join-Path $workingRootFull 'installer'
$testAppId = '{{' + [Guid]::NewGuid().ToString().ToUpperInvariant() + '}'

function Invoke-Installer {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [string[]]$AdditionalArguments = @(),
        [switch]$ExpectFailure
    )

    $arguments = @(
        '/SP-',
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/CURRENTUSER',
        '/NOICONS'
    ) + $AdditionalArguments
    $process = Start-Process `
        -FilePath $Path `
        -ArgumentList $arguments `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    if ($ExpectFailure) {
        if ($process.ExitCode -eq 0) {
            throw "Der Installer hätte abbrechen müssen: $Path"
        }
    }
    elseif ($process.ExitCode -ne 0) {
        throw "Installer fehlgeschlagen ($($process.ExitCode)): $Path"
    }
}

function Get-InstalledVersion {
    $registryRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'
    $entry = Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue |
        ForEach-Object {
            Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
        } |
        Where-Object {
            $property = $_.PSObject.Properties['InstallLocation']
            $null -ne $property -and
            [System.IO.Path]::GetFullPath([string]$property.Value).TrimEnd('\') -eq
                $installRoot.TrimEnd('\')
        } |
        Select-Object -First 1
    if ($null -eq $entry) {
        return $null
    }
    return [string]$entry.PSObject.Properties['DisplayVersion'].Value
}

function Assert-InstalledVersion {
    param([Parameter(Mandatory = $true)][string]$Expected)

    $actual = Get-InstalledVersion
    if ($actual -ne $Expected) {
        throw "Installierte Version $actual statt $Expected gefunden."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $installRoot 'SacrificialTower.exe'))) {
        throw 'Die installierte Programmdatei fehlt.'
    }
}

function Build-TestInstaller {
    param([Parameter(Mandatory = $true)][string]$BuildVersion)

    $baseName = "SacrificialTower-Replacement-$BuildVersion"
    & $isccFull `
        '/Qp' `
        "/DAppVersion=$BuildVersion" `
        "/DAppIdValue=$testAppId" `
        "/DDefaultInstallDir=$installRoot" `
        "/DStandaloneUserDataDir=$userDataRoot" `
        "/DInstallerOutputDir=$outputRoot" `
        "/DInstallerOutputBaseFilename=$baseName" `
        '/DUninstallIntegrationTest=1' `
        $scriptPath | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Test-Installer für Version $BuildVersion konnte nicht gebaut werden."
    }
    $path = Join-Path $outputRoot ($baseName + '.exe')
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Test-Installer fehlt: $path"
    }
    return $path
}

function Remove-TestInstallation {
    $uninstaller = Get-ChildItem `
        -LiteralPath $installRoot `
        -Filter 'unins*.exe' `
        -File `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $uninstaller) {
        return
    }
    $process = Start-Process `
        -FilePath $uninstaller.FullName `
        -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        Write-Warning "Test-Deinstallation endete mit Code $($process.ExitCode)."
    }
}

if (Test-Path -LiteralPath $workingRootFull) {
    Remove-Item -LiteralPath $workingRootFull -Recurse -Force
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

try {
    $olderInstaller = Build-TestInstaller -BuildVersion $olderVersion
    $currentInstaller = Build-TestInstaller -BuildVersion $Version

    Invoke-Installer -Path $olderInstaller
    Assert-InstalledVersion -Expected $olderVersion

    Invoke-Installer -Path $currentInstaller
    Assert-InstalledVersion -Expected $Version

    New-Item -ItemType Directory -Path $userDataRoot -Force | Out-Null
    $dataMarker = Join-Path $userDataRoot 'settings.keep'
    Set-Content -LiteralPath $dataMarker -Value 'persönliche Einstellungen' -Encoding utf8

    Invoke-Installer -Path $currentInstaller -ExpectFailure
    Assert-InstalledVersion -Expected $Version

    Invoke-Installer `
        -Path $currentInstaller `
        -AdditionalArguments @('/TESTACCEPTREPLACEMENT')
    Assert-InstalledVersion -Expected $Version
    if (-not (Test-Path -LiteralPath $dataMarker)) {
        throw 'Die Neuinstallation derselben Version hat persönliche Daten gelöscht.'
    }

    Invoke-Installer -Path $olderInstaller -ExpectFailure
    Assert-InstalledVersion -Expected $Version

    Invoke-Installer `
        -Path $olderInstaller `
        -AdditionalArguments @('/TESTACCEPTREPLACEMENT')
    Assert-InstalledVersion -Expected $olderVersion
    if (-not (Test-Path -LiteralPath $dataMarker)) {
        throw 'Das bestätigte Downgrade hat beizubehaltende Daten gelöscht.'
    }

    Invoke-Installer -Path $currentInstaller
    Assert-InstalledVersion -Expected $Version

    Invoke-Installer `
        -Path $olderInstaller `
        -AdditionalArguments @(
            '/TESTACCEPTREPLACEMENT',
            '/TESTDELETEUSERDATA'
        )
    Assert-InstalledVersion -Expected $olderVersion
    if (Test-Path -LiteralPath $userDataRoot) {
        throw 'Das bestätigte Downgrade hat die angeforderte Datenlöschung ausgelassen.'
    }

}
finally {
    Remove-TestInstallation
    if (Test-Path -LiteralPath $workingRootFull) {
        Remove-Item -LiteralPath $workingRootFull -Recurse -Force
    }
}

Write-Host 'Installer-Ersetzungstest erfolgreich.'
