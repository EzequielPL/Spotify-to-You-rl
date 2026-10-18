#!/usr/bin/env python3
"""
spotify_to_yourl.py
──────────────────────────────
Punto de entrada clásico (CLI). La lógica vive en el paquete spotyurl/.

    python spotify_to_yourl.py "https://open.spotify.com/playlist/ID"
    python spotify_to_yourl.py --help

Para la interfaz gráfica:  python -m spotyurl.gui
"""

import sys

from spotyurl.cli import main

if __name__ == "__main__":
    sys.exit(main())
