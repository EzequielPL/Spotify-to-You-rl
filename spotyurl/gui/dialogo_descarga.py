"""Diálogo de «Descargar audio»: carpeta, nombre de la subcarpeta, formato y quitadas."""

import html
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from ..download import CARPETA_QUITADAS, FORMATOS_AUDIO
from ..manifiesto import claves_unicas, leer_manifiesto
from ..models import Track
from ..paths import safe_filename
from .constantes import plural


def contar_quitadas(folder: Path, tracks: list[Track]) -> int:
    """Canciones del manifiesto de `folder` (con su archivo aún ahí) que ya no están en `tracks`."""
    manifiesto = leer_manifiesto(folder)
    if not manifiesto:
        return 0
    en_lista = set(claves_unicas(tracks))
    return sum(1 for clave, e in manifiesto["canciones"].items()
               if clave not in en_lista and (Path(folder) / e["archivo"]).exists())


class DialogoDescarga(QDialog):
    def __init__(self, n: int, salida: Path, nombre: str, formato: str, con_ffmpeg: bool, parent=None,
                 tracks: list[Track] | None = None):
        super().__init__(parent)
        # Lista completa: sirve para ver si la carpeta destino tiene canciones que ya no están
        self._tracks = tracks or []
        self.setWindowTitle("Descargar audio")
        self.setMinimumWidth(460)
        self.salida = salida   # carpeta de audio elegida (la ventana la guarda en ajustes)

        self.info = QLabel(wordWrap=True)
        self._n = n
        self._texto_info()
        cambiar = QPushButton("Cambiar…")
        cambiar.setToolTip("Elegir otra carpeta de audio (se recuerda para la próxima vez)")
        cambiar.clicked.connect(self._cambiar_salida)
        fila_info = QHBoxLayout()
        fila_info.addWidget(self.info, 1)
        fila_info.addWidget(cambiar)
        nota = QLabel("Cada lista se descarga en una subcarpeta con su nombre.", objectName="muted", wordWrap=True)
        self.nombre = QLineEdit(nombre)
        self.nombre.selectAll()
        self.formato = QComboBox()
        for clave, desc in FORMATOS_AUDIO.items():
            self.formato.addItem(desc, clave)
        self.formato.setCurrentIndex(max(0, self.formato.findData(formato)))
        if not con_ffmpeg:
            # Sin ffmpeg no se puede convertir: se guarda lo que dé YouTube
            self.formato.setEnabled(False)
            self.formato.setToolTip("No se encontró ffmpeg: vuelve a ejecutar instalar")

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("Nombre de la carpeta", self.nombre)
        form.addRow("Formato", self.formato)

        # Solo aparece si la carpeta destino ya es una descarga con canciones que ya no están en la lista
        self.quitadas = QCheckBox()
        self.quitadas.setToolTip("Si no se marca, se dejan donde están (se avisan en el log)")
        self.lbl_existe = QLabel(objectName="muted", wordWrap=True)

        self.botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botones.button(QDialogButtonBox.Ok).setText("Descargar")
        self.botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)
        self.nombre.textChanged.connect(self._validar)

        lay = QVBoxLayout(self)
        lay.addLayout(fila_info)
        lay.addWidget(nota)
        if not con_ffmpeg:
            lay.addWidget(QLabel(
                "ffmpeg no está disponible: el audio se guardará en .m4a/.webm.\n"
                "Vuelve a ejecutar instalar para poder elegir el formato.",
                objectName="muted", wordWrap=True,
            ))
        lay.addSpacing(4)
        lay.addLayout(form)
        lay.addWidget(self.lbl_existe)
        lay.addWidget(self.quitadas)
        lay.addSpacing(8)
        lay.addWidget(self.botones)
        self._validar()

    def _texto_info(self):
        verbo = "Se descargará" if self._n == 1 else "Se descargarán"
        self.info.setText(f"{verbo} {plural(self._n, 'canción', 'canciones')} en una carpeta nueva dentro de:"
                          f"<br><b>{html.escape(str(self.salida))}</b>")

    def _cambiar_salida(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de audio", str(self.salida))
        if d:
            self.salida = Path(d)
            self._texto_info()
            self._validar()

    def _validar(self):
        self.botones.button(QDialogButtonBox.Ok).setEnabled(bool(self.carpeta()))
        self._comprobar_destino()

    def _comprobar_destino(self):
        destino = self.salida / self.carpeta() if self.carpeta() else None
        existe = destino is not None and leer_manifiesto(destino) is not None
        self.lbl_existe.setText("Esta carpeta ya tiene una descarga: solo se bajarán las canciones nuevas "
                                "y se renumerarán las demás." if existe else "")
        self.lbl_existe.setVisible(existe)
        n = contar_quitadas(destino, self._tracks) if existe else 0
        self.quitadas.setText(f"Mover a «{CARPETA_QUITADAS}» las {n} canciones que ya no están en la lista"
                              if n != 1 else
                              f"Mover a «{CARPETA_QUITADAS}» la canción que ya no está en la lista")
        self.quitadas.setVisible(n > 0)
        if not n:
            self.quitadas.setChecked(False)

    def mover_quitadas(self) -> bool:
        return self.quitadas.isVisibleTo(self) and self.quitadas.isChecked()

    def carpeta(self) -> str:
        return safe_filename(self.nombre.text())

    def formato_elegido(self) -> str:
        return self.formato.currentData()
