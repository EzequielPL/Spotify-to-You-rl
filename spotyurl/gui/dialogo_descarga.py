"""Diálogo de «Descargar audio»: nombre de la carpeta y formato."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from ..download import FORMATOS_AUDIO
from ..paths import safe_filename


class DialogoDescarga(QDialog):
    def __init__(self, n: int, salida: Path, nombre: str, formato: str, con_ffmpeg: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Descargar audio")
        self.setMinimumWidth(460)

        info = QLabel(
            f"Se descargarán {n} canciones en una carpeta nueva dentro de:<br><b>{salida}</b><br>"
            "<span style='opacity:.7'>Puedes cambiarla en Ajustes → Carpeta de audio.</span>",
            wordWrap=True,
        )
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

        self.botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botones.button(QDialogButtonBox.Ok).setText("Descargar")
        self.botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)
        self.nombre.textChanged.connect(self._validar)

        lay = QVBoxLayout(self)
        lay.addWidget(info)
        if not con_ffmpeg:
            lay.addWidget(QLabel(
                "ffmpeg no está disponible: el audio se guardará en .m4a/.webm.\n"
                "Vuelve a ejecutar instalar para poder elegir el formato.",
                objectName="muted", wordWrap=True,
            ))
        lay.addSpacing(4)
        lay.addLayout(form)
        lay.addSpacing(8)
        lay.addWidget(self.botones)
        self._validar()

    def _validar(self):
        self.botones.button(QDialogButtonBox.Ok).setEnabled(bool(self.carpeta()))

    def carpeta(self) -> str:
        return safe_filename(self.nombre.text())

    def formato_elegido(self) -> str:
        return self.formato.currentData()
