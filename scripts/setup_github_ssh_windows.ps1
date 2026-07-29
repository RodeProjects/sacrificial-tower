[CmdletBinding()]
param(
    [string]$RepositoryPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$KeyName = 'id_ed25519_github_rodeprojects_laptop',
    [string]$KeyTitle = "RodeProjects-$env:COMPUTERNAME-Windows11"
)

$ErrorActionPreference = 'Stop'

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)]
        [string]$FilePath,
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [Parameter(Mandatory)]
        [string]$Description
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description ist mit Exitcode $LASTEXITCODE fehlgeschlagen."
    }
}

$git = (Get-Command git -ErrorAction Stop).Source
$sshKeygen = (Get-Command ssh-keygen -ErrorAction Stop).Source
$windowsDirectory = [Environment]::GetFolderPath('Windows')
$ssh = Join-Path $windowsDirectory 'System32\OpenSSH\ssh.exe'
if (-not (Test-Path -LiteralPath $ssh -PathType Leaf)) {
    $ssh = (Get-Command ssh -ErrorAction Stop).Source
}

$repositoryRoot = (& $git -C $RepositoryPath rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repositoryRoot) {
    throw "Unter '$RepositoryPath' wurde kein Git-Repository gefunden."
}

$origin = (& $git -C $repositoryRoot remote get-url origin).Trim()
if (
    $LASTEXITCODE -ne 0 -or
    $origin -notmatch 'github\.com[:/]RodeProjects/sacrificial-tower(?:\.git)?$'
) {
    throw "Das Repository gehoert nicht zu RodeProjects/sacrificial-tower: $origin"
}

$userProfile = [Environment]::GetFolderPath('UserProfile')
$sshDirectory = Join-Path $userProfile '.ssh'
New-Item -ItemType Directory -Path $sshDirectory -Force | Out-Null
$keyPath = Join-Path $sshDirectory $KeyName
$publicKeyPath = "$keyPath.pub"

$privateKeyExists = Test-Path -LiteralPath $keyPath -PathType Leaf
$publicKeyExists = Test-Path -LiteralPath $publicKeyPath -PathType Leaf
if ($privateKeyExists -xor $publicKeyExists) {
    throw "Das Schluesselpaar ist unvollstaendig. Pruefe '$keyPath' und '$publicKeyPath'."
}
if (-not $privateKeyExists) {
    Invoke-NativeCommand -FilePath $sshKeygen -Arguments @(
        '-t', 'ed25519',
        '-f', $keyPath,
        '-N', '',
        '-C', $KeyTitle
    ) -Description 'Die SSH-Schluesselerzeugung'
}

$sshExecutable = $ssh.Replace('\', '/')
$normalizedKeyPath = $keyPath.Replace('\', '/')
$sshCommand = "`"$sshExecutable`" -i `"$normalizedKeyPath`" -o IdentitiesOnly=yes"
Invoke-NativeCommand -FilePath $git -Arguments @(
    '-C', $repositoryRoot,
    'config', '--local', 'core.sshCommand', $sshCommand
) -Description 'Die Repository-spezifische SSH-Konfiguration'
Invoke-NativeCommand -FilePath $git -Arguments @(
    '-C', $repositoryRoot,
    'remote', 'set-url', 'origin',
    'git@github.com:RodeProjects/sacrificial-tower.git'
) -Description 'Die Umstellung des Git-Remotes auf SSH'

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -ne $gh) {
    Invoke-NativeCommand -FilePath $gh.Source -Arguments @(
        'config', 'set', 'git_protocol', 'ssh'
    ) -Description 'Die GitHub-CLI-Konfiguration'
}

$publicKey = (Get-Content -LiteralPath $publicKeyPath -Raw).Trim()
Write-Host ''
Write-Host 'Die lokale SSH-Einrichtung ist abgeschlossen.' -ForegroundColor Green
Write-Host 'Hinterlege diesen oeffentlichen Schluessel einmalig unter:'
Write-Host 'https://github.com/settings/ssh/new' -ForegroundColor Cyan
Write-Host ''
Write-Host "Titel: $KeyTitle"
Write-Host "Schluessel: $publicKey"
Write-Host ''
Write-Host 'Danach testen:'
Write-Host "ssh -T -i `"$keyPath`" -o IdentitiesOnly=yes git@github.com"
Write-Host "git -C `"$repositoryRoot`" ls-remote origin HEAD"
Write-Host ''
Write-Host 'Fuer GitHub-CLI-Funktionen ist auf diesem Geraet zusaetzlich genau einmal noetig:'
Write-Host 'gh auth login --git-protocol ssh --web'
