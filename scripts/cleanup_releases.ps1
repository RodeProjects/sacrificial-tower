[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$LatestVersion,

    [string]$ConfigPath,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $projectRoot 'config\release_retention.json'
}
$configFull = (Resolve-Path -LiteralPath $ConfigPath).Path
$planner = Join-Path $PSScriptRoot 'release_retention.py'

$ghCommand = Get-Command gh -ErrorAction SilentlyContinue
if ($null -ne $ghCommand) {
    $gh = $ghCommand.Source
} else {
    $gh = 'C:\Program Files\GitHub CLI\gh.exe'
}
if (-not (Test-Path -LiteralPath $gh)) {
    throw 'GitHub CLI wurde nicht gefunden.'
}
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $python = (Resolve-Path -LiteralPath $venvPython).Path
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw 'Python wurde für die Release-Bereinigung nicht gefunden.'
    }
    $python = $pythonCommand.Source
}

function Assert-NativeSuccess {
    param([Parameter(Mandatory = $true)][string]$Action)

    if ($LASTEXITCODE -ne 0) {
        throw "$Action ist fehlgeschlagen (Exitcode $LASTEXITCODE)."
    }
}

$mainChannel = & $python -c "import sys; sys.path.insert(0, sys.argv[1]); from cooling_tower.update_channel import RELEASE_REPOSITORY; print(RELEASE_REPOSITORY)" (Join-Path $projectRoot 'src')
Assert-NativeSuccess 'Das Lesen des zentralen Releasekanals'
if ($Repository -ceq $mainChannel -and -not $DryRun) {
    throw 'Unveränderliche Hauptrepository-Releases und ihre Quellcode-Tags werden nicht automatisch bereinigt.'
}

& $gh auth status
Assert-NativeSuccess 'Die GitHub-Anmeldeprüfung'

$temporaryRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) ('sacrificial-tower-retention-' + [guid]::NewGuid().ToString('N'))
$resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
$resolvedSystemTemp = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
)
if (-not $resolvedTemporaryRoot.StartsWith(
    $resolvedSystemTemp,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw 'Temporäres Bereinigungsverzeichnis liegt außerhalb des System-Temp-Ordners.'
}
New-Item -ItemType Directory -Path $resolvedTemporaryRoot | Out-Null

try {
    $allReleases = @()
    $page = 1
    do {
        $response = & $gh api (
            "repos/$Repository/releases?per_page=100&page=$page"
        )
        Assert-NativeSuccess "Das Lesen der Release-Seite $page"
        $parsedPage = ConvertFrom-Json -InputObject ($response -join "`n")
        $batch = @(
            foreach ($release in $parsedPage) {
                $release
            }
        )
        $allReleases += $batch
        $page += 1
    } while ($batch.Count -eq 100)

    $releasesPath = Join-Path $resolvedTemporaryRoot 'releases.json'
    $planPath = Join-Path $resolvedTemporaryRoot 'plan.json'
    ConvertTo-Json -InputObject @($allReleases) -Depth 20 |
        Set-Content -LiteralPath $releasesPath -Encoding utf8

    & $python $planner `
        --config $configFull `
        --releases $releasesPath `
        --output $planPath `
        --latest-version $LatestVersion
    Assert-NativeSuccess 'Das Planen der Release-Bereinigung'

    $plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
    $beforeGiB = [math]::Round(
        [double]$plan.total_asset_size_bytes_before / 1GB,
        3
    )
    $afterGiB = [math]::Round(
        [double]$plan.total_asset_size_bytes_after / 1GB,
        3
    )
    Write-Host (
        "Release-Aufbewahrung: $($plan.release_count_before) -> " +
        "$($plan.release_count_after) Releases, $beforeGiB -> $afterGiB GiB."
    )

    $deletions = @($plan.delete)
    foreach ($release in $deletions) {
        $mode = if ($DryRun) { 'Würde löschen' } else { 'Lösche' }
        Write-Host (
            "$mode Release $($release.tag_name): $($release.reason), " +
            "$($release.asset_size_bytes) Bytes."
        )
        if (-not $DryRun) {
            & $gh api `
                --method DELETE `
                "repos/$Repository/releases/$($release.id)"
            Assert-NativeSuccess "Das Löschen von Release $($release.tag_name)"
        }
    }

    if (-not [bool]$plan.capacity_limit_satisfied) {
        $limitGiB = [math]::Round(
            [double]$plan.maximum_total_asset_size_bytes / 1GB,
            3
        )
        throw (
            "Die $limitGiB-GiB-Grenze kann nicht eingehalten werden, ohne " +
            'eines der ' +
            'mindestens aufzubewahrenden oder geschützten Releases zu löschen.'
        )
    }
}
finally {
    if (
        (Test-Path -LiteralPath $resolvedTemporaryRoot) -and
        $resolvedTemporaryRoot.StartsWith(
            $resolvedSystemTemp,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}

if ($DryRun) {
    Write-Host 'Probelauf der Release-Bereinigung erfolgreich.'
} else {
    Write-Host 'Release-Bereinigung erfolgreich.'
}
