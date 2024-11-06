Set WshShell = CreateObject("WScript.Shell")

' Sprawdź status repozytorium
WshShell.Run "git status", 0, True

' Pobierz aktualizacje
WshShell.Run "git pull", 0, True

' Zainstaluj wymagane pakiety
WshShell.Run "pip install -r requirements.txt", 0, True

' Uruchom aplikację
WshShell.Run "app.py", 0
