@echo off
chcp 65001 >nul
setlocal
rem Instala (o actualiza) todo lo necesario: entorno virtual, dependencias y Chromium.
rem Se puede ejecutar varias veces: la segunda vez solo actualiza.
cd /d "%~dp0"

set "VENV=Spoty_to_you-rl"
set "VPY=%VENV%\Scripts\python.exe"

echo ==========================================
echo   Spotify a YouTube - Instalacion
echo ==========================================
echo.

rem --- 1. Buscar Python 3.10 o superior ---
set "PYCMD="
py -3 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo [ERROR] No se encontro Python 3.10 o superior.
    echo.
    echo Instalalo desde https://www.python.org/downloads/
    echo   ^(marca "Add python.exe to PATH" durante la instalacion^)
    echo o desde una terminal con:
    echo   winget install Python.Python.3.13
    echo.
    echo Despues vuelve a ejecutar instalar.bat
    echo.
    pause
    exit /b 1
)
echo Python encontrado: %PYCMD%

rem --- 2. Crear el entorno virtual (o rehacerlo si esta roto) ---
if exist "%VPY%" (
    "%VPY%" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo El entorno virtual "%VENV%" esta roto. Se vuelve a crear...
        rmdir /s /q "%VENV%"
    )
)
if not exist "%VPY%" (
    echo Creando el entorno virtual "%VENV%"...
    %PYCMD% -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)

rem --- 3. Dependencias ---
echo.
echo Actualizando pip...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] No se pudo actualizar pip. Revisa tu conexion a internet.
    pause
    exit /b 1
)

echo.
echo Instalando dependencias ^(requirements.txt^)...
"%VPY%" -m pip install -r "requirements.txt"
if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias. Revisa tu conexion a internet.
    pause
    exit /b 1
)

echo.
echo Instalando Chromium para Playwright...
"%VPY%" -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] No se pudo instalar Chromium ^(Playwright^). Revisa tu conexion a internet.
    pause
    exit /b 1
)

rem --- 4. ffmpeg (opcional) ---
echo.
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [Aviso] ffmpeg no esta instalado. Es opcional: solo hace falta para guardar el audio en .mp3.
    echo         Para instalarlo:  winget install ffmpeg
) else (
    echo ffmpeg encontrado.
)

echo.
echo ==========================================
echo   Listo. Abre la app con abrir_app.bat
echo ==========================================
echo.
pause
endlocal
