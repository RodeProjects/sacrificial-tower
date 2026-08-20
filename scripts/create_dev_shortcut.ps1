[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ShortcutPath = ""
)

$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $ShortcutPath) {
    $ShortcutPath = Join-Path $resolvedProjectRoot "Sacrificial Tower starten.lnk"
}
$shortcutFullPath = [IO.Path]::GetFullPath($ShortcutPath)
$pythonwPath = Join-Path $resolvedProjectRoot ".venv\Scripts\pythonw.exe"
$launcherPath = Join-Path $resolvedProjectRoot "start_gui.pyw"
$iconPath = Join-Path $resolvedProjectRoot "src\cooling_tower\gui\assets\app.ico"

foreach ($requiredPath in @($pythonwPath, $launcherPath, $iconPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Erforderliche Launcher-Datei fehlt: $requiredPath"
    }
}

$shortcutDirectory = Split-Path -Parent $shortcutFullPath
if ($shortcutDirectory) {
    New-Item -ItemType Directory -Path $shortcutDirectory -Force | Out-Null
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutFullPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '"' + $launcherPath + '"'
$shortcut.WorkingDirectory = $resolvedProjectRoot
$shortcut.IconLocation = $iconPath + ",0"
$shortcut.Description = "Sacrificial Tower (Entwicklungsumgebung)"
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Output $shortcutFullPath
