param(
    [string]$SourceRepository = "RodeProjects/sacrificial-tower",
    [string]$UpdateRepository = "RodeProjects/sacrificial-tower-updates"
)

$ErrorActionPreference = "Stop"
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

& $gh auth status

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

if (git status --porcelain) {
    throw "Der Arbeitsbaum muss vor der Veröffentlichung sauber sein."
}
$localCommit = git rev-parse HEAD
$remoteCommit = & $gh api "repos/$SourceRepository/commits/main" --jq .sha
if ($localCommit -ne $remoteCommit) {
    throw "Der lokale Commit entspricht nicht dem veröffentlichten main-Branch."
}

& $gh workflow run build-update.yml `
    --repo $SourceRepository `
    --ref main `
    -f "version=$version"

$run = $null
for ($attempt = 0; $attempt -lt 20 -and $null -eq $run; $attempt++) {
    Start-Sleep -Seconds 2
    $runs = & $gh run list `
        --repo $SourceRepository `
        --workflow build-update.yml `
        --event workflow_dispatch `
        --limit 10 `
        --json databaseId,headSha,createdAt | ConvertFrom-Json
    $run = $runs |
        Where-Object { $_.headSha -eq $localCommit } |
        Sort-Object createdAt -Descending |
        Select-Object -First 1
}
if ($null -eq $run) {
    throw "Der gestartete Build-Workflow wurde nicht gefunden."
}

& $gh run watch $run.databaseId --repo $SourceRepository --exit-status

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

try {
    $artifactName = "SacrificialTower-$version-windows-x64"
    & $gh run download $run.databaseId `
        --repo $SourceRepository `
        --name $artifactName `
        --dir $resolvedTemporaryRoot

    $metadataPath = Join-Path $resolvedTemporaryRoot "update-metadata.json"
    $metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
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

    & $gh release create $tag $installer.FullName `
        --repo $UpdateRepository `
        --title "Sacrificial Tower $version" `
        --notes "Automatisches Windows-Update auf Version $version."

    $manifest = @{
        schema_version = 1
        version = $version
        installer_url = (
            "https://github.com/$UpdateRepository/releases/download/" +
            "$tag/$($installer.Name)"
        )
        sha256 = $actualHash
        size_bytes = $installer.Length
        release_notes = "Sacrificial Tower $version"
    } | ConvertTo-Json
    $manifestBytes = [System.Text.Encoding]::UTF8.GetBytes($manifest + "`n")
    $encodedManifest = [Convert]::ToBase64String($manifestBytes)

    $existingSha = $null
    try {
        $existingSha = & $gh api `
            "repos/$UpdateRepository/contents/latest.json" `
            --jq .sha
    } catch {
        $existingSha = $null
    }
    $apiArguments = @(
        "api",
        "repos/$UpdateRepository/contents/latest.json",
        "--method", "PUT",
        "-f", "message=Update channel to $version",
        "-f", "content=$encodedManifest",
        "-f", "branch=main"
    )
    if ($existingSha) {
        $apiArguments += @("-f", "sha=$existingSha")
    }
    & $gh @apiArguments | Out-Null
    Write-Host "Version $version wurde im öffentlichen Update-Kanal veröffentlicht."
} finally {
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
