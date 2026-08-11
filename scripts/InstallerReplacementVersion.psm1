Set-StrictMode -Version Latest

function Get-OlderInstallerTestVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidatePattern('^\d+\.\d+\.\d+$')]
        [string]$Version
    )

    $versionParts = $Version.Split('.')
    $majorVersion = [int]$versionParts[0]
    $minorVersion = [int]$versionParts[1]
    $patchVersion = [int]$versionParts[2]

    if ($patchVersion -gt 0) {
        return '{0}.{1}.{2}' -f (
            $majorVersion,
            $minorVersion,
            ($patchVersion - 1)
        )
    }
    if ($minorVersion -gt 0) {
        return '{0}.{1}.0' -f $majorVersion, ($minorVersion - 1)
    }
    if ($majorVersion -gt 0) {
        return '{0}.0.0' -f ($majorVersion - 1)
    }

    throw 'Für Version 0.0.0 existiert keine ältere Testversion.'
}

Export-ModuleMember -Function Get-OlderInstallerTestVersion
