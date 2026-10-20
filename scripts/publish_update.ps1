param(
    [string]$SourceRepository = "RodeProjects/sacrificial-tower",
    [string]$UpdateRepository = "RodeProjects/sacrificial-tower-updates",
    [switch]$DevelopmentRelease,
    [switch]$AllowTimedOutCI,
    [string]$RunnerToolsRoot = (Join-Path $PSScriptRoot '..\..\_Tools\github_actions_runner')
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

$releaseWorkflowHelper = Join-Path $RunnerToolsRoot 'scripts\Invoke-ReleaseWorkflow.ps1'
if (-not (Test-Path -LiteralPath $releaseWorkflowHelper -PathType Leaf)) {
    throw "Der zentrale offizielle Runner-Releasehelfer fehlt: $releaseWorkflowHelper"
}
if (-not $AllowTimedOutCI) {
    $releaseTests = & $releaseWorkflowHelper `
        -Repository $SourceRepository -Workflow 'tests.yml' `
        -Ref main -ExpectedSha $localCommit
    if ($releaseTests.conclusion -ne 'success' -or $releaseTests.headSha -ne $localCommit) {
        throw 'Die vollständige Releaseprüfung bestätigt den Release-Commit nicht.'
    }
}
$run = & $releaseWorkflowHelper `
    -Repository $SourceRepository -Workflow 'build-update.yml' `
    -Ref main -ExpectedSha $localCommit `
    -Inputs @{
        version = $version
        release_kind = $releaseKind
        allow_timed_out_ci = $AllowTimedOutCI.IsPresent
    }
if ($run.conclusion -ne 'success' -or $run.headSha -ne $localCommit) {
    throw 'Der Build-Workflow bestätigt den Release-Commit nicht.'
}

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

    $releaseSummary = (
        "Sacrificial Tower is a free Windows 3D printing cooling tower tool and G-code analyzer " +
        "for minimum layer time optimization. Supports Anycubic Slicer Next, Bambu Studio, " +
        "PrusaSlicer and OrcaSlicer. Configure your printer in a supported slicer before use."
    )
    if ($DevelopmentRelease) {
        $releaseTitle = "Sacrificial Tower $version (Entwicklungsversion)"
        $releaseNotes = (
            $releaseSummary + "`n`nKostenlose Entwicklungsversion " +
            "für Tests und Evaluation. Offene Anbieter- und Vertriebsangaben " +
            "werden vor einer regulären kostenlosen Veröffentlichung nachgetragen."
        )
    } else {
        $releaseTitle = "Sacrificial Tower $version"
        $releaseNotes = $releaseSummary + "`n`nSacrificial-Tower-Update auf Version $version."
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
