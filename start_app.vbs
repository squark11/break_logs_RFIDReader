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
KillProcess "python.exe" ' Upewnij się, że to proces uruchamiający app.py

' Sprawdź status repozytorium
WshShell.Run "git status", 0, True

' Pobierz aktualizacje
WshShell.Run "git fetch --all", 0, True
WshShell.Run "git reset --hard origin/main", 0, True

' Zainstaluj wymagane pakiety
WshShell.Run "pip install -r requirements.txt", 0, True

' Uruchom aplikację
WshShell.Run "python C:\break_logs_RFIDReader\app.py", 0
