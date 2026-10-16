param(
    [string]$SourceRepository = "RodeProjects/sacrificial-tower",
    [string]$UpdateRepository = "RodeProjects/sacrificial-tower-updates",
    [switch]$DevelopmentRelease,
    [switch]$AllowTimedOutCI
)

$ErrorActionPreference = "Stop"
if ($AllowTimedOutCI -and -not $DevelopmentRelease) {
    throw "Die CI-Zeitlimit-Ausnahme ist nur für Entwicklungsreleases zulässig."
}
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

$ghCommand = Get-Command gh -ErrorAction SilentlyContinue
if ($null -ne $ghCommand) {
    $gh = $ghCommand.Source
} else {
    $gh = "C:\Program Files\GitHub CLI\gh.exe"
}
if (-not (Test-Path -LiteralPath $gh)) {
    throw "GitHub CLI wurde nicht gefunden."
}
$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $python = (Resolve-Path -LiteralPath $venvPython).Path
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Python wurde für die Signaturprüfung nicht gefunden."
    }
    $python = $pythonCommand.Source
}

function Assert-NativeSuccess {
    param([string]$Action)
    if ($LASTEXITCODE -ne 0) {
        throw "$Action ist fehlgeschlagen (Exitcode $LASTEXITCODE)."
    }
}

if ($DevelopmentRelease) {
    & $python `
        (Join-Path $PSScriptRoot "check_release_readiness.py") `
        --development-release
    Assert-NativeSuccess "Die Freigabeprüfung für Entwicklungsversionen"
    $releaseKind = "development"
} else {
    & $python (Join-Path $PSScriptRoot "check_release_readiness.py") --release
    Assert-NativeSuccess "Die Anbieter- und Vertriebsfreigabeprüfung"
    $releaseKind = "free"
}

& $gh auth status
Assert-NativeSuccess "Die GitHub-Anmeldeprüfung"

$versionSource = Get-Content "src\cooling_tower\version.py" -Raw
$versionMatch = [regex]::Match(
    $versionSource,
    'APP_VERSION\s*=\s*"(?<version>[0-9]+\.[0-9]+\.[0-9]+)"'
)
if (-not $versionMatch.Success) {
    throw "APP_VERSION konnte nicht gelesen werden."
}
$version = $versionMatch.Groups["version"].Value
$tag = "v$version"

$worktreeStatus = git status --porcelain
Assert-NativeSuccess "Die Prüfung des Git-Arbeitsbaums"
if ($worktreeStatus) {
    throw "Der Arbeitsbaum muss vor der Veröffentlichung sauber sein."
}
$localCommit = git rev-parse HEAD
Assert-NativeSuccess "Das Lesen des lokalen Commits"
$remoteCommit = & $gh api "repos/$SourceRepository/commits/main" --jq .sha
Assert-NativeSuccess "Das Lesen des veröffentlichten main-Commits"
if ($localCommit -ne $remoteCommit) {
    throw "Der lokale Commit entspricht nicht dem veröffentlichten main-Branch."
}

& $gh workflow run build-update.yml `
    --repo $SourceRepository `
    --ref main `
    -f "version=$version" `
    -f "release_kind=$releaseKind" `
    -f "allow_timed_out_ci=$($AllowTimedOutCI.IsPresent.ToString().ToLowerInvariant())"
Assert-NativeSuccess "Das Starten des Build-Workflows"

$run = $null
for ($attempt = 0; $attempt -lt 20 -and $null -eq $run; $attempt++) {
    Start-Sleep -Seconds 2
    $runsJson = & $gh run list `
        --repo $SourceRepository `
        --workflow build-update.yml `
        --event workflow_dispatch `
        --limit 10 `
        --json databaseId,headSha,createdAt
    Assert-NativeSuccess "Das Lesen der Build-Workflow-Läufe"
    $runs = $runsJson | ConvertFrom-Json
    $run = $runs |
        Where-Object { $_.headSha -eq $localCommit } |
        Sort-Object createdAt -Descending |
        Select-Object -First 1
}
if ($null -eq $run) {
    throw "Der gestartete Build-Workflow wurde nicht gefunden."
}

& $gh run watch $run.databaseId --repo $SourceRepository --compact --exit-status --interval 15
Assert-NativeSuccess "Der Build-Workflow"

$temporaryRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("sacrificial-tower-publish-" + [guid]::NewGuid().ToString("N"))
$resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
$resolvedSystemTemp = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
)
if (-not $resolvedTemporaryRoot.StartsWith(
    $resolvedSystemTemp,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Temporäres Veröffentlichungsverzeichnis liegt außerhalb des System-Temp-Ordners."
}
New-Item -ItemType Directory -Path $resolvedTemporaryRoot | Out-Null

$releaseCreated = $false
$manifestPublished = $false
try {
    $artifactName = "SacrificialTower-$version-windows-x64"
    & $gh run download $run.databaseId `
        --repo $SourceRepository `
        --name $artifactName `
        --dir $resolvedTemporaryRoot
    Assert-NativeSuccess "Das Herunterladen des Build-Artefakts"

    $metadataPath = Join-Path $resolvedTemporaryRoot "update-metadata.json"
    $manifestPath = Join-Path $resolvedTemporaryRoot "latest.json"
    $metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($metadata.version -ne $version) {
        throw "Die Version des Build-Artefakts stimmt nicht überein."
    }
    $installer = Get-Item (
        Join-Path $resolvedTemporaryRoot $metadata.installer_name
    )
    $actualHash = (
        Get-FileHash $installer.FullName -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($actualHash -ne $metadata.sha256 -or $installer.Length -ne $metadata.size_bytes) {
        throw "Die Integritätsprüfung des Build-Artefakts ist fehlgeschlagen."
    }
    if (
        $manifest.version -ne $version -or
        $manifest.sha256 -ne $actualHash -or
        $manifest.size_bytes -ne $installer.Length
    ) {
        throw "Das signierte Update-Manifest stimmt nicht mit dem Build-Artefakt überein."
    }
    & $python `
        (Join-Path $PSScriptRoot "verify_update_manifest.py") `
        --manifest $manifestPath `
        --installer $installer.FullName
    Assert-NativeSuccess "Die kryptografische Prüfung des Update-Manifests"

    if ($DevelopmentRelease) {
        $releaseTitle = "Sacrificial Tower $version (Entwicklungsversion)"
        $releaseNotes = (
            "Kostenlose Entwicklungsversion " +
            "für Tests und Evaluation. Offene Anbieter- und Vertriebsangaben " +
            "werden vor einer regulären kostenlosen Veröffentlichung nachgetragen."
        )
    } else {
        $releaseTitle = "Sacrificial Tower $version"
        $releaseNotes = "Sacrificial-Tower-Update auf Version $version."
    }
    $releaseArguments = @(
        "release", "create", $tag, $installer.FullName,
        "--repo", $UpdateRepository,
        "--title", $releaseTitle,
        "--notes", $releaseNotes,
        "--latest"
    )
    & $gh @releaseArguments
    Assert-NativeSuccess "Das Erstellen des Sacrificial-Tower-Releases"
    $releaseCreated = $true

    $manifestBytes = [System.IO.File]::ReadAllBytes($manifestPath)
    $encodedManifest = [Convert]::ToBase64String($manifestBytes)

    $existingSha = $null
    try {
        $existingSha = & $gh api `
            "repos/$UpdateRepository/contents/latest.json" `
            --jq .sha
        Assert-NativeSuccess "Das Lesen des bestehenden Programmupdate-Manifests"
    } catch {
        $existingSha = $null
    }
    $apiArguments = @(
        "api",
        "repos/$UpdateRepository/contents/latest.json",
        "--method", "PUT",
        "-f", "message=Programmupdate-Kanal auf Version $version aktualisieren",
        "-f", "content=$encodedManifest",
        "-f", "branch=main"
    )
    if ($existingSha) {
        $apiArguments += @("-f", "sha=$existingSha")
    }
    & $gh @apiArguments | Out-Null
    Assert-NativeSuccess "Das Aktualisieren des Programmupdate-Manifests"
    $manifestPublished = $true

    & (Join-Path $PSScriptRoot 'cleanup_releases.ps1') `
        -Repository $UpdateRepository `
        -LatestVersion $version
    Assert-NativeSuccess 'Die automatische Release-Bereinigung'
    Write-Host (
        "Version $version wurde als $releaseKind im öffentlichen " +
        "Update-Kanal veröffentlicht."
    )
} finally {
    if ($releaseCreated -and -not $manifestPublished) {
        & $gh release delete $tag `
            --repo $UpdateRepository `
            --yes
        if ($LASTEXITCODE -ne 0) {
            Write-Warning (
                "Das unvollständig veröffentlichte Release $tag konnte nicht " +
                "automatisch entfernt werden."
            )
        }
    }
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
