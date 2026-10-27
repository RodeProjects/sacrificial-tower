#Requires -Version 7.4
param(
    [string]$SourceRepository = "",
    [string]$UpdateRepository = "",
    [switch]$DevelopmentRelease,
    [switch]$AllowTimedOutCI,
    [string]$RunnerToolsRoot = (Join-Path $PSScriptRoot '..\..\_Tools\github_actions_runner')
)

$ErrorActionPreference = "Stop"
if ($AllowTimedOutCI -and -not $DevelopmentRelease) {
    throw "Die CI-Zeitlimit-Ausnahme ist nur für Entwicklungsreleases zulässig."
}
if ($AllowTimedOutCI) {
    throw 'Die frühere CI-Zeitlimit-Ausnahme wird durch den nachgewiesenen privaten offiziellen Fallback ersetzt. Ohne diesen Prüferfolg ist keine Veröffentlichung zulässig.'
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

$channelRepository = & $python -c "import sys; sys.path.insert(0, 'src'); from cooling_tower.update_channel import RELEASE_REPOSITORY; print(RELEASE_REPOSITORY)"
Assert-NativeSuccess 'Das Lesen des zentralen Updatekanals'
if (-not $SourceRepository) { $SourceRepository = $channelRepository }
if (-not $UpdateRepository) { $UpdateRepository = $channelRepository }
if ($SourceRepository -cne $channelRepository -or $UpdateRepository -cne $channelRepository) {
    throw 'Quellstand und Updatekanal müssen das zentral konfigurierte Hauptrepository verwenden.'
}
$immutable = & $gh api "repos/$SourceRepository/immutable-releases" | ConvertFrom-Json
Assert-NativeSuccess 'Die Prüfung unveränderlicher Releases'
if (-not $immutable.enabled) { throw 'Vor einer Veröffentlichung müssen unveränderliche Releases aktiviert sein.' }

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
$existingReleases = & $gh api "repos/$SourceRepository/releases?per_page=100" | ConvertFrom-Json
Assert-NativeSuccess 'Die Prüfung vorhandener Releases'
if (@($existingReleases | Where-Object tag_name -CEQ $tag).Count) {
    throw 'Diese Releaseversion ist bereits belegt und wird nicht überschrieben.'
}

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
$releasePublished = $false
$releaseId = 0L
try {
    $artifactHelper = Join-Path $RunnerToolsRoot 'scripts/Get-PrivateBuildArtifacts.ps1'
    if (-not (Test-Path -LiteralPath $artifactHelper -PathType Leaf)) {
        throw 'Der geschützte zentrale Artefaktübernahmehelfer fehlt.'
    }
    & $artifactHelper -Repository $SourceRepository -ExpectedSha $localCommit `
        -RunId $run.databaseId -Operation 'build-update.yml' `
        -Destination $resolvedTemporaryRoot

    $metadataPath = Join-Path $resolvedTemporaryRoot "update-metadata.json"
    $manifestPath = Join-Path $resolvedTemporaryRoot "latest.json"
    $metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
    if ($metadata.version -cne $version -or
        $metadata.installer_name -cne "SacrificialTowerSetup-$version.exe" -or
        $metadata.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        ($metadata.size_bytes -isnot [long] -and $metadata.size_bytes -isnot [int]) -or
        $metadata.size_bytes -le 0) {
        throw "Version, Dateiname oder Integritätsangaben des Build-Artefakts sind ungültig."
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
    $currentRemote = & $gh api "repos/$SourceRepository/commits/main" --jq .sha
    Assert-NativeSuccess 'Die erneute Prüfung des Release-Commits'
    if ($currentRemote -cne $localCommit -or (git rev-parse HEAD) -cne $localCommit -or (git status --porcelain)) {
        throw 'Projektcommit oder main wurde während des Builds verändert. Keine Veröffentlichung.'
    }
    $signingHelper = Join-Path $RunnerToolsRoot 'scripts/Sign-UpdateManifest.ps1'
    $manifestNotes = if ($DevelopmentRelease) { "Sacrificial Tower $version – Entwicklungsversion für Tests und Evaluation" } else { "Sacrificial Tower $version" }
    & $signingHelper -RepositoryPath (Split-Path $PSScriptRoot -Parent) -MetadataPath $metadataPath -OutputPath $manifestPath -UpdateRepository $UpdateRepository -ReleaseNotes $manifestNotes
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
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

    $releaseSummaryDe = @'
**Sacrificial Tower - Erstellung dynamischer Opferobjekte passend zur gewünschten Layerzeit**

Bei kurzen Layerzeiten kann beim FDM-/FFF-3D-Druck zu wenig Zeit zum Abkühlen bleiben. Sacrificial Tower erstellt dafür einen zusätzlichen Kühlturm (bzw. ein Opferobjekt): Er wird neben deinem Modell mitgedruckt und erzeugt durch seine dynamische Form an den nötigen Stellen zusätzliche Layerzeit.

Das kostenlose Windows-Programm wertet die Layerzeiten deines STL-Modells mit dem gewählten Slicer aus und bietet zwei Wege zum passenden Turm:

- **Automatisch:** Die gewünschte Layerzeit vorgeben und die Berechnung über zusätzliche Einstellungen beeinflussen; das Programm passt die Turmform anhand wiederholter Slices schrittweise an, um die Zielzeit möglichst genau zu erreichen.
- **Manuell:** Die Turmform einfach in einem visuellen Editor selbst gestalten und die daraus resultierenden Layerzeiten mit dem gewählten Slicer prüfen lassen

Wie gut ein automatisch erstellter Turm die gewünschte Layerzeit erreicht, hängt maßgeblich von den im Programm gewählten Profilen und deren Einstellungen ab.

Beide Modi speichern Modell und Kühlturm als gemeinsames **3MF-Projekt** für deinen Slicer. Die Turm-STL wird zusätzlich exportiert.

Unterstützt werden **Anycubic Slicer Next, Bambu Studio, PrusaSlicer und OrcaSlicer**. Installiere einen dieser Slicer und richte darin deinen Drucker ein. Öffne das exportierte 3MF im gewählten Slicer und prüfe vor dem Druck Anordnung und Einstellungen. Getestete Versionen und Details stehen in der [Projektbeschreibung](https://github.com/RodeProjects/sacrificial-tower#unterst%C3%BCtzte-slicer-und-getestete-versionen).
'@
    $releaseSummaryEn = @'
**Sacrificial Tower / Cooling Tower Generator - Creating dynamic sacrificial objects tailored to your desired layer time**

Short layer times can leave too little time for cooling in FDM/FFF 3D printing. Sacrificial Tower creates an additional cooling tower (a sacrificial object), printed alongside your model. Its dynamic shape adds layer time where needed.

This free Windows application for FDM/FFF 3D printing evaluates your STL model's layer times using your selected slicer and offers two ways to create your tower:

- **Automatic:** Set your desired layer time and influence the calculation through additional settings; the application gradually adjusts the tower shape based on repeated slices to get as close as possible to the target time.
- **Manual:** Easily shape the tower yourself in a visual editor and let your selected slicer check the resulting layer times.

How closely an automatically generated tower matches your desired layer time depends substantially on the profiles selected in the application and their settings.

Both modes save your model and cooling tower as a single **3MF project** for your slicer. A separate tower STL is also exported.

Supports **Anycubic Slicer Next, Bambu Studio, PrusaSlicer and OrcaSlicer**. Install one of these slicers and configure your printer in it first. Open the exported 3MF in the selected slicer and check the arrangement and settings before printing. See the [project description](https://github.com/RodeProjects/sacrificial-tower#unterst%C3%BCtzte-slicer-und-getestete-versionen) for tested versions and details.
'@
    if ($DevelopmentRelease) {
        $releaseTitle = "Sacrificial Tower $version (Entwicklungsversion)"
        $releaseStatusDe = (
            "Kostenlose Entwicklungsversion " +
            "für Tests und Evaluation. Offene Anbieter- und Vertriebsangaben " +
            "werden vor einer regulären kostenlosen Veröffentlichung nachgetragen."
        )
        $releaseStatusEn = (
            "Free development version for testing and evaluation. Outstanding provider and " +
            "distribution details will be completed before a regular free release."
        )
    } else {
        $releaseTitle = "Sacrificial Tower $version"
        $releaseStatusDe = "Sacrificial-Tower-Update auf Version $version."
        $releaseStatusEn = "Sacrificial Tower update to version $version."
    }
    $releaseNotes = $releaseSummaryDe.Trim() + "`n`n" + $releaseStatusDe
    $releaseNotes += "`n`nQuellcode: $SourceRepository, Tag $tag, Commit $localCommit.`nInstaller und signiertes latest.json gehören unveränderlich zu diesem Release."
    $releaseNotes += "`n`n---`n`n" + $releaseSummaryEn.Trim() + "`n`n" + $releaseStatusEn
    $releaseNotes += "`n`nSource: $SourceRepository, tag $tag, commit $localCommit.`nThe installer and signed latest.json are immutable assets of this release."
    $notesPath=Join-Path $resolvedTemporaryRoot 'release-notes.md'
    [IO.File]::WriteAllText($notesPath,$releaseNotes,[Text.UTF8Encoding]::new($false))
    $legalRoot=Join-Path $resolvedTemporaryRoot 'legal-texts'
    & $python (Join-Path $PSScriptRoot 'export_legal_documents.py') --output $legalRoot
    Assert-NativeSuccess 'Der Export aufgelöster öffentlicher Rechtstexte'
    $legalArchive=Join-Path $resolvedTemporaryRoot 'legal-texts.zip'
    [IO.Compression.ZipFile]::CreateFromDirectory($legalRoot,$legalArchive)

    git remote -v
    git branch --show-current
    git status -sb
    if((git remote get-url origin) -cne "git@github.com:$SourceRepository.git") {throw 'Unerwarteter SSH-Remote vor dem Release-Tag.'}
    $commitMessage=git show -s --format=%s $localCommit
    Assert-NativeSuccess 'Das Lesen der bereits geprüften Commitnachricht'
    Write-Host "Commitnachricht des unverändert geprüften Release-Commits: $commitMessage"
    $remoteTag=git ls-remote origin "refs/tags/$tag"
    Assert-NativeSuccess 'Die Prüfung des Remote-Tags'
    if(-not $remoteTag) {
        $localTags=@(git tag --list $tag)
        Assert-NativeSuccess 'Die Prüfung lokaler Tags'
        if($localTags.Count) {
            if((git rev-parse "$tag^{commit}") -cne $localCommit){throw 'Vorhandener lokaler Tag zeigt auf anderen Quellcode.'}
        } else {
            git tag -a $tag $localCommit -m "Sacrificial Tower $version ($releaseKind)"
            Assert-NativeSuccess 'Das Erstellen des Quellcode-Tags'
        }
        git push origin "refs/tags/$tag"
        Assert-NativeSuccess 'Das Pushen des geprüften Quellcode-Tags'
    }
    function Assert-SourceTag {
        $reference=& $gh api "repos/$SourceRepository/git/ref/tags/$tag" | ConvertFrom-Json
        Assert-NativeSuccess 'Die serverseitige Tagprüfung'
        $object=$reference.object
        if($object.type -ceq 'tag') {
            $annotation=& $gh api "repos/$SourceRepository/git/tags/$($object.sha)" | ConvertFrom-Json
            Assert-NativeSuccess 'Die Prüfung des annotierten Tags'
            $object=$annotation.object
        }
        if($object.type -cne 'commit' -or $object.sha -cne $localCommit){throw 'Release-Tag stimmt nicht mit dem geprüften Quellcommit überein.'}
    }
    Assert-SourceTag
    # The tag endpoint only resolves published releases. Keep the concrete ID
    # returned when creating this invocation's unpublished draft.
    $requestPath=Join-Path $resolvedTemporaryRoot 'release-request.json'
    $request=@{tag_name=$tag;target_commitish=$localCommit;draft=$true;prerelease=$false;name=$releaseTitle;body=$releaseNotes}
    [IO.File]::WriteAllText($requestPath,($request|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
    $created=& $gh api --method POST "repos/$SourceRepository/releases" --input $requestPath | ConvertFrom-Json
    Assert-NativeSuccess 'Das Anlegen des Releaseentwurfs'
    if($created.id -le 0 -or -not $created.draft -or $created.tag_name -cne $tag -or $created.target_commitish -cne $localCommit){throw 'GitHub bestätigt keinen eindeutig zugeordneten Releaseentwurf.'}
    $releaseId=[long]$created.id
    $releaseCreated=$true
    foreach($assetFile in @($installer.FullName,$manifestPath,$legalArchive)) {
        $assetName=[Uri]::EscapeDataString([IO.Path]::GetFileName($assetFile))
        $null=& $gh api --method POST -H 'Content-Type: application/octet-stream' `
            "https://uploads.github.com/repos/$SourceRepository/releases/$releaseId/assets?name=$assetName" --input $assetFile
        Assert-NativeSuccess 'Das Hochladen eines nachgewiesenen Releaseanhangs'
    }
    $draft=& $gh api "repos/$SourceRepository/releases/$releaseId" | ConvertFrom-Json
    Assert-NativeSuccess 'Die Prüfung des Releaseentwurfs anhand seiner ID'
    $expected=@{
        $installer.Name=@{hash=$actualHash;size=$installer.Length}
        'latest.json'=@{hash=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant();size=(Get-Item -LiteralPath $manifestPath).Length}
        'legal-texts.zip'=@{hash=(Get-FileHash -LiteralPath $legalArchive -Algorithm SHA256).Hash.ToLowerInvariant();size=(Get-Item -LiteralPath $legalArchive).Length}
    }
    if(-not $draft.draft -or $draft.prerelease -or @($draft.assets).Count -ne $expected.Count){throw 'Releaseentwurf enthält nicht den erwarteten Lieferumfang.'}
    foreach($asset in $draft.assets) {
        if(-not $expected.ContainsKey($asset.name) -or $asset.size -ne $expected[$asset.name].size -or $asset.digest -cne ('sha256:'+$expected[$asset.name].hash)) {throw 'GitHub bestätigt keinen passenden Hash und Umfang der Release-Anhänge.'}
    }
    $currentRemote=& $gh api "repos/$SourceRepository/commits/main" --jq .sha
    Assert-NativeSuccess 'Die abschließende Prüfung des Release-Commits'
    if($currentRemote -cne $localCommit -or (git rev-parse HEAD) -cne $localCommit -or (git status --porcelain)){throw 'Quellstand während der Releasevorbereitung verändert.'}
    Assert-SourceTag
    $published=& $gh api --method PATCH "repos/$SourceRepository/releases/$releaseId" -F draft=false -f make_latest=true | ConvertFrom-Json
    Assert-NativeSuccess 'Das Veröffentlichen des unveränderlichen Entwicklungs-/Programmreleases'
    $releasePublished=$true
    if($published.draft -or $published.prerelease -or -not $published.immutable -or $published.tag_name -cne $tag){throw 'GitHub bestätigt kein unveränderliches geeignetes Release.'}
    Assert-SourceTag
    $roundtrip=Join-Path $resolvedTemporaryRoot 'published-download'
    New-Item -ItemType Directory -Path $roundtrip | Out-Null
    & $gh release download $tag --repo $SourceRepository --dir $roundtrip --pattern $installer.Name --pattern latest.json
    Assert-NativeSuccess 'Der tatsächliche Download der veröffentlichten Dateien'
    & $python (Join-Path $PSScriptRoot 'verify_update_manifest.py') --manifest (Join-Path $roundtrip 'latest.json') --installer (Join-Path $roundtrip $installer.Name)
    Assert-NativeSuccess 'Die Signatur-/Integritätsprüfung des veröffentlichten Downloads'
    if((Get-FileHash -LiteralPath (Join-Path $roundtrip $installer.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $actualHash){throw 'Veröffentlichter Installer weicht vom geprüften Build ab.'}
    Write-Host "Version $version als $releaseKind in $SourceRepository veröffentlicht; Tag, Assets, tatsächlicher Download und Signatur bestätigt."
} finally {
    if($releaseCreated -and $releaseId -gt 0 -and -not $releasePublished) {
        # An ambiguous publishing response may already have locked the release.
        # Delete only this invocation's still-unpublished draft, never a release.
        try {
            $remaining=& $gh api "repos/$SourceRepository/releases/$releaseId" | ConvertFrom-Json
            Assert-NativeSuccess 'Die Prüfung eines unvollständigen Releaseentwurfs'
            if($remaining.draft -and $remaining.id -eq $releaseId -and $remaining.tag_name -ceq $tag) {
                & $gh api --method DELETE "repos/$SourceRepository/releases/$releaseId"
                Assert-NativeSuccess 'Das Entfernen des unveröffentlichten Entwurfs'
            }
        } catch { Write-Warning 'Releasezustand konnte nicht abschließend geprüft werden; keine unbekannte Veröffentlichung gelöscht.' }
    }
    $prefix=$resolvedSystemTemp.TrimEnd('\')+'\'
    if((Test-Path -LiteralPath $resolvedTemporaryRoot) -and $resolvedTemporaryRoot.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -and
       -not (Get-Item -LiteralPath $resolvedTemporaryRoot).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}
