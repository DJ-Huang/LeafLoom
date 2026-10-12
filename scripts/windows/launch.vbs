Option Explicit
Dim shell, files, action, script, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
action = WScript.Arguments(0)
If action <> "open" And action <> "stop" And action <> "install" Then WScript.Quit 1
script = files.BuildPath(files.GetParentFolderName(WScript.ScriptFullName), "launch.ps1")
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """ -Action " & action
' Detach the hidden controller so the original .cmd window can close immediately.
shell.Run command, 0, False
