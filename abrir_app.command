#!/bin/bash
# Abre la interfaz gráfica en macOS (doble clic en Finder).
# Usa el entorno virtual del proyecto (lo crea instalar.command).
cd "$(dirname "$0")" || exit 1

for PY in "Spoty_to_you-rl/bin/python" ".venv/bin/python"; do
    if [ -x "$PY" ]; then
        exec "$PY" -m spotyurl.gui
    fi
done

echo "No se encontró el entorno virtual \"Spoty_to_you-rl\"."
echo "Primero ejecuta instalar.command (doble clic; la primera vez, clic derecho → Abrir) y vuelve a abrir la app."
read -r -p "Pulsa Enter para cerrar…"
exit 1
