"""Diálogo de ajustes."""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from .ajustes import DEFAULTS, Ajustes
from .constantes import CACHE_PATH


# ── Diálogo de ajustes ───────────────────────────────────────────────────────

class DialogoAjustes(QDialog):
    def __init__(self, ajustes: Ajustes, parent=None):
        super().__init__(parent)
        self.ajustes = ajustes
        self.setWindowTitle("Ajustes")
        self.setMinimumWidth(480)

        self.mostrar_nav = QCheckBox("Mostrar el navegador durante la extracción (depuración)")
        self.mostrar_nav.setChecked(not ajustes["headless"])
        self.n_results = QSpinBox(minimum=1, maximum=10, value=ajustes["n_results"])
        self.plantilla = QLineEdit(ajustes["query_template"])
        self.plantilla.setToolTip("Variables: {artist}, {title}, {album}")
        self.scroll_pausa = QDoubleSpinBox(minimum=0.2, maximum=5, singleStep=0.1, value=ajustes["scroll_pause"], suffix=" s")
        self.fin_vueltas = QSpinBox(minimum=2, maximum=40, value=ajustes["end_rounds"])
        self.usar_cache = QCheckBox("Recordar búsquedas anteriores (más rápido)")
        self.usar_cache.setChecked(ajustes["use_cache"])
        self.auto_guardar = QCheckBox("Guardar .txt automáticamente al terminar")
        self.auto_guardar.setChecked(ajustes["auto_save"])
        self.carpeta = QLineEdit(ajustes["out_dir"])
        self.carpeta_audio = QLineEdit(ajustes["audio_dir"])
        self.carpeta_audio.setToolTip("Cada playlist se descarga en una subcarpeta con su nombre")
        vaciar = QPushButton("Vaciar caché de búsquedas")
        vaciar.clicked.connect(self._vaciar_cache)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("Carpeta de salida", self._fila_carpeta(self.carpeta, "Carpeta de salida"))
        form.addRow("", self.auto_guardar)
        form.addRow("Carpeta de audio", self._fila_carpeta(self.carpeta_audio, "Carpeta de audio"))
        form.addRow("Búsqueda en YouTube", self.plantilla)
        form.addRow("Candidatos por canción", self.n_results)
        form.addRow("", self.usar_cache)
        form.addRow("", vaciar)
        form.addRow("Pausa de scroll", self.scroll_pausa)
        form.addRow("Vueltas sin cambios para parar", self.fin_vueltas)
        form.addRow("", self.mostrar_nav)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addSpacing(8)
        lay.addWidget(botones)

    def _fila_carpeta(self, campo: QLineEdit, titulo: str) -> QHBoxLayout:
        examinar = QPushButton("Examinar…")
        examinar.clicked.connect(lambda: self._elegir_carpeta(campo, titulo))
        fila = QHBoxLayout()
        fila.addWidget(campo, 1)
        fila.addWidget(examinar)
        return fila

    def _elegir_carpeta(self, campo: QLineEdit, titulo: str):
        d = QFileDialog.getExistingDirectory(self, titulo, campo.text())
        if d:
            campo.setText(d)

    def _vaciar_cache(self):
        CACHE_PATH.unlink(missing_ok=True)
        QMessageBox.information(self, "Caché", "Caché de búsquedas vaciada.")

    def accept(self):
        a = self.ajustes
        a["headless"] = not self.mostrar_nav.isChecked()
        a["n_results"] = self.n_results.value()
        a["query_template"] = self.plantilla.text().strip() or DEFAULTS["query_template"]
        a["scroll_pause"] = self.scroll_pausa.value()
        a["end_rounds"] = self.fin_vueltas.value()
        a["use_cache"] = self.usar_cache.isChecked()
        a["auto_save"] = self.auto_guardar.isChecked()
        a["out_dir"] = self.carpeta.text().strip() or DEFAULTS["out_dir"]
        a["audio_dir"] = self.carpeta_audio.text().strip() or DEFAULTS["audio_dir"]
        super().accept()
