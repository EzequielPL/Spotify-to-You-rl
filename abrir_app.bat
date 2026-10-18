@echo off
rem Abre la interfaz grafica usando el entorno virtual del proyecto
cd /d "%~dp0"
if exist "Spoty_to_you-rl\Scripts\pythonw.exe" (
    start "" "Spoty_to_you-rl\Scripts\pythonw.exe" -m spotyurl.gui
) else (
    start "" pythonw -m spotyurl.gui
)
