Option Explicit

Dim shell, fileSystem, projectRoot, pythonwPath, launcherPath, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = projectRoot & "\.venv\Scripts\pythonw.exe"
launcherPath = projectRoot & "\start_gui.pyw"
command = Chr(34) & pythonwPath & Chr(34) & " " & Chr(34) & launcherPath & Chr(34)

' Window style 0 keeps the launcher completely hidden; False returns at once.
shell.Run command, 0, False
