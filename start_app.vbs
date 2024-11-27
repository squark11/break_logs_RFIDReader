Set WshShell = CreateObject("WScript.Shell")

' Funkcja do zamykania poprzednich instancji app.py
Sub KillProcess(processName)
    Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
    Set colProcesses = objWMIService.ExecQuery("Select * from Win32_Process Where Name = '" & processName & "'")
    
    For Each objProcess In colProcesses
        objProcess.Terminate()
    Next
End Sub

' Zamknij poprzednie uruchomienia app.py
KillProcess "python.exe"

' Ścieżka do katalogu projektu
projectPath = "C:\break_logs_RFIDReader"

' Sprawdź status repozytorium
WshShell.CurrentDirectory = projectPath
WshShell.Run "git status", 0, True

' Pobierz aktualizacje
WshShell.Run "git fetch --all", 0, True
WshShell.Run "git reset --hard origin/main", 0, True

' Zainstaluj wymagane pakiety w środowisku wirtualnym (jeśli jest używane)
WshShell.Run "cmd /c python -m pip install -r requirements.txt", 0, True

' Uruchom aplikację (upewnij się, że używasz pełnej ścieżki do Pythona, jeśli to konieczne)
WshShell.Run "cmd /c python " & projectPath & "\app.py", 0
