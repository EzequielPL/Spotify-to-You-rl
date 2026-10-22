#!/bin/bash
# Instala (o actualiza) todo lo necesario en macOS: entorno virtual, dependencias y Chromium.
# Doble clic en Finder. Se puede ejecutar varias veces: la segunda vez solo actualiza.
cd "$(dirname "$0")" || exit 1

VENV="Spoty_to_you-rl"
VPY="$VENV/bin/python"

salir() {
    echo
    read -r -p "Pulsa Enter para cerrar…"
    exit "${1:-0}"
}

fallo() {
    echo
    echo "[ERROR] $1"
    salir 1
}

echo "=========================================="
echo "  Spotify → YouTube · Instalación"
echo "=========================================="
echo

# --- 1. Buscar Python 3.10 o superior ---
PYCMD=""
for CAND in python3 python; do
    if command -v "$CAND" >/dev/null 2>&1 &&
       "$CAND" -c "import sys; sys.exit(sys.version_info < (3,10))" >/dev/null 2>&1; then
        PYCMD="$(command -v "$CAND")"
        break
    fi
done
if [ -z "$PYCMD" ]; then
    echo "[ERROR] No se encontró Python 3.10 o superior."
    echo
    echo "Instálalo desde https://www.python.org/downloads/macos/"
    echo "o con Homebrew:  brew install python"
    echo
    echo "Después vuelve a ejecutar instalar.command"
    salir 1
fi
echo "Python encontrado: $PYCMD ($("$PYCMD" --version 2>&1))"

# --- 2. Crear el entorno virtual (o rehacerlo si está roto) ---
if [ -e "$VPY" ] && ! "$VPY" -c "import sys" >/dev/null 2>&1; then
    echo "El entorno virtual \"$VENV\" está roto. Se vuelve a crear…"
    rm -rf "$VENV"
fi
if [ ! -x "$VPY" ]; then
    echo "Creando el entorno virtual \"$VENV\"…"
    "$PYCMD" -m venv "$VENV" || fallo "No se pudo crear el entorno virtual."
fi

# --- 3. Dependencias ---
echo
echo "Actualizando pip…"
"$VPY" -m pip install --upgrade pip ||
    fallo "No se pudo actualizar pip. Revisa tu conexión a internet."

echo
echo "Instalando dependencias (requirements.txt)…"
"$VPY" -m pip install -r requirements.txt ||
    fallo "No se pudieron instalar las dependencias. Revisa tu conexión a internet."

echo
echo "Instalando Chromium para Playwright…"
"$VPY" -m playwright install chromium ||
    fallo "No se pudo instalar Chromium (Playwright). Revisa tu conexión a internet."

# --- 4. ffmpeg (opcional) ---
echo
if command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg encontrado."
else
    echo "[Aviso] ffmpeg no está instalado. Es opcional: solo hace falta para guardar el audio en .mp3."
    echo "        Para instalarlo:  brew install ffmpeg"
fi

echo
echo "=========================================="
echo "  Listo. Abre la app con abrir_app.command"
echo "=========================================="
salir 0
