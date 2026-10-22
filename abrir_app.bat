@echo off
rem Abre la interfaz grafica usando el entorno virtual del proyecto
cd /d "%~dp0"
if not exist "Spoty_to_you-rl\Scripts\pythonw.exe" (
    chcp 65001 >nul
    echo No se encontro el entorno virtual "Spoty_to_you-rl".
    echo Primero ejecuta instalar.bat ^(doble clic^) y vuelve a abrir la app.
    echo.
    pause
    exit /b 1
)
start "" "Spoty_to_you-rl\Scripts\pythonw.exe" -m spotyurl.gui
