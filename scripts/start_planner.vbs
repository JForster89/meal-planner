' Launches the planner with no console flash at all.
' The desktop shortcut points here via wscript.exe.
Dim shell, fso, here
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
' 0 = hidden window, False = don't wait for it to finish
shell.Run """" & here & "\start_planner.bat""", 0, False
