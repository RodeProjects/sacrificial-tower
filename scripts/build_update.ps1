[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory)][ValidateSet('development','free')][string]$ReleaseKind
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$appVersion = & $Python -c "import sys; sys.path.insert(0, 'src'); from cooling_tower.version import APP_VERSION; print(APP_VERSION)"
if ($appVersion -cne $Version) { throw 'Buildversion stimmt nicht mit APP_VERSION überein.' }
$readiness = if ($ReleaseKind -eq 'development') { '--development-release' } else { '--release' }
& $Python scripts/check_release_readiness.py $readiness
& $Python scripts/prepare_qt_sources.py
& $Python -m PyInstaller --noconfirm --clean SacrificialTower.spec
& $Python scripts/distribution_compliance.py --bundle dist/SacrificialTower --output dist/installer/build-inventory.json
$innoInstaller = Join-Path $env:RUNNER_TEMP 'innosetup-6.7.3.exe'
$innoRoot = Join-Path $env:RUNNER_TEMP 'InnoSetup'
Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $innoInstaller
if ((Get-FileHash -LiteralPath $innoInstaller -Algorithm SHA256).Hash.ToLowerInvariant() -cne '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732') { throw 'Inno-Setup-Hash stimmt nicht überein.' }
$process = Start-Process -FilePath $innoInstaller -ArgumentList "/PORTABLE=1 /VERYSILENT /CURRENTUSER /DIR=`"$innoRoot`"" -Wait -WindowStyle Hidden -PassThru
if ($process.ExitCode) { throw 'Inno-Setup-Einrichtung fehlgeschlagen.' }
$iscc = Join-Path $innoRoot 'ISCC.exe'
$env:INNO_ROOT = $innoRoot
& $iscc "/DAppVersion=$appVersion" "/DAppPublisherName=$((Get-Content -LiteralPath 'config/legal_profile.json' -Raw | ConvertFrom-Json).provider_name)" installer/SacrificialTower.iss
& $Python -m unittest discover -s tests -p test_update_handoff_native.py -v
& ./scripts/test_installer_license.ps1 -IsccPath $iscc
& ./scripts/test_uninstaller.ps1 -IsccPath $iscc -Version $appVersion
& ./scripts/test_installer_replacement.ps1 -IsccPath $iscc -Version $appVersion
$installer = Get-Item -LiteralPath "dist/installer/SacrificialTowerSetup-$appVersion.exe"
@{version=$appVersion;installer_name=$installer.Name;sha256=(Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant();size_bytes=$installer.Length} |
    ConvertTo-Json | Set-Content -LiteralPath dist/installer/update-metadata.json -Encoding utf8
# Signing is deliberately performed later by the protected publishing process.
