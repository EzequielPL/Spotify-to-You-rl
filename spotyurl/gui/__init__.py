"""
Interfaz gráfica (PySide6).

    python -m spotyurl.gui

Todo el trabajo pesado (Playwright + yt-dlp) corre en un único QThread que
habla con la UI mediante señales; la UI nunca toca Playwright. La descarga de
audio usa otro QThread (DownloadWorker) con las mismas señales.

Módulos (sin ciclos; ninguno importa este __init__):
    constantes, tema       hojas
    ajustes, modelo        ajustes persistentes y modelo de la tabla
    workers                hilos de extracción/búsqueda y descarga
    dialogo_ajustes        diálogo de ajustes
    ventana                ventana principal
    app                    main()
"""

from .ajustes import DEFAULTS, Ajustes
from .app import main
from .constantes import CACHE_PATH, COLOR_ESTADO, ICON_PATH
from .dialogo_ajustes import DialogoAjustes
from .modelo import FiltroTracks, TrackTableModel
from .tema import aplicar_tema
from .ventana import MainWindow
from .workers import DownloadWorker, Worker

__all__ = [
    "DEFAULTS", "Ajustes", "main", "CACHE_PATH", "COLOR_ESTADO", "ICON_PATH", "DialogoAjustes",
    "FiltroTracks", "TrackTableModel", "aplicar_tema", "MainWindow", "DownloadWorker", "Worker",
]
