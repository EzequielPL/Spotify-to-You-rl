"""
Interfaz gráfica (PySide6).

    python -m spotyurl.gui

Todo el trabajo pesado (Playwright + yt-dlp) corre en un único QThread que
habla con la UI mediante señales; la UI nunca toca Playwright. La descarga de
audio usa otro QThread (DownloadWorker) con las mismas señales.

Módulos (sin ciclos; ninguno importa este __init__):
    constantes, tema       hojas
    ajustes, modelo        ajustes persistentes y modelo de la tabla
    workers                hilos de extracción/búsqueda, descarga y candidatos
    dialogo_ajustes        diálogo de ajustes
    dialogo_descarga       diálogo de «Descargar audio»
    dialogo_candidatos     diálogo de «Elegir otra versión»
    dialogo_actualizar     diálogo de «Actualizar yt-dlp»
    ventana                ventana principal
    app                    main()
"""

from .ajustes import DEFAULTS, Ajustes
from .app import main
from .constantes import CACHE_PATH, ICON_PATH
from .dialogo_actualizar import DialogoActualizar
from .dialogo_ajustes import DialogoAjustes
from .dialogo_candidatos import DialogoCandidatos
from .modelo import FiltroTracks, TrackTableModel
from .tema import aplicar_tema, colores_estado
from .ventana import MainWindow
from .workers import CandidatosWorker, DownloadWorker, Worker

__all__ = [
    "DEFAULTS", "Ajustes", "main", "CACHE_PATH", "ICON_PATH", "DialogoActualizar", "DialogoAjustes", "DialogoCandidatos", "colores_estado",
    "FiltroTracks", "TrackTableModel", "aplicar_tema", "MainWindow", "CandidatosWorker", "DownloadWorker", "Worker",
]
