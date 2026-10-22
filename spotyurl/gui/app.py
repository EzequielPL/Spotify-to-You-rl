"""Punto de entrada de la interfaz gráfica."""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import __version__
from .ajustes import Ajustes
from .constantes import ICON_PATH
from .tema import aplicar_tema
from .ventana import MainWindow


def main() -> int:
    if sys.platform == "win32":
        # Sin esto, Windows agrupa la ventana bajo python.exe y muestra su icono en la barra de tareas
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("spotyurl.SpotifyToYourl")
    app = QApplication(sys.argv)
    app.setApplicationName("Spotify to You-rl")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyle("Fusion")
    aplicar_tema(app, Ajustes()["theme"])
    win = MainWindow()
    win.show()
    return app.exec()
