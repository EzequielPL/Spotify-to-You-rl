#!/bin/bash
# Abre la interfaz gráfica en macOS (doble clic en Finder).
# Usa el entorno virtual del proyecto si existe; si no, python3 del sistema.
cd "$(dirname "$0")" || exit 1

for PY in "Spoty_to_you-rl/bin/python" ".venv/bin/python" "$(command -v python3)"; do
    if [ -x "$PY" ]; then
        exec "$PY" -m spotyurl.gui
    fi
done

echo "No se encontró Python 3. Instálalo desde https://www.python.org o con Homebrew (brew install python)."
read -r -p "Pulsa Enter para cerrar…"
