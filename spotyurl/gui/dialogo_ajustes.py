"""Diálogo de ajustes."""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from .. import actualizar
from .ajustes import DEFAULTS, Ajustes
from .constantes import CACHE_PATH
from .dialogo_actualizar import abrir_actualizar, texto_version


# ── Diálogo de ajustes ───────────────────────────────────────────────────────

class DialogoAjustes(QDialog):
    def __init__(self, ajustes: Ajustes, parent=None):
        super().__init__(parent)
        self.ajustes = ajustes
        self.setWindowTitle("Ajustes")
        self.setMinimumWidth(480)
        self.grupos: list[QGroupBox] = []

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
        self.clip = QCheckBox("Copiar cada enlace al portapapeles")
        self.clip.setToolTip("Útil con MediaHuman u otros gestores que detectan enlaces del portapapeles.\n"
                             "Solo se copian las encontradas y las manuales, no las dudosas.")
        self.clip.setChecked(ajustes["clipboard"])
        self.pausa = QDoubleSpinBox(minimum=0, maximum=10, singleStep=0.5, value=ajustes["pause"], suffix=" s")
        self.pausa.setToolTip("Espera entre una copia y la siguiente para que el gestor las detecte todas")
        self.clip.toggled.connect(self.pausa.setEnabled)
        self.pausa.setEnabled(self.clip.isChecked())
        vaciar = QPushButton("Vaciar caché de búsquedas")
        vaciar.clicked.connect(self._vaciar_cache)

        carpetas = self._grupo("Carpetas")
        carpetas.addRow("Carpeta de salida", self._fila_carpeta(self.carpeta, "Carpeta de salida"))
        carpetas.addRow("", self.auto_guardar)
        carpetas.addRow("Carpeta de audio", self._fila_carpeta(self.carpeta_audio, "Carpeta de audio"))
        portapapeles = self._grupo("Portapapeles (MediaHuman)")
        portapapeles.addRow("", self.clip)
        portapapeles.addRow("Pausa entre enlaces", self.pausa)
        busqueda = self._grupo("Búsqueda")
        busqueda.addRow("Búsqueda en YouTube", self.plantilla)
        busqueda.addRow("Candidatos por canción", self.n_results)
        busqueda.addRow("", self.usar_cache)
        busqueda.addRow("", vaciar)
        avanzado = self._grupo("Avanzado")
        avanzado.addRow("Pausa de scroll", self.scroll_pausa)
        avanzado.addRow("Vueltas sin cambios para parar", self.fin_vueltas)
        avanzado.addRow("", self.mostrar_nav)
        # yt-dlp: los errores 403 / «nsig» / «not a bot» suelen arreglarse actualizándolo
        self.lbl_ytdlp = QLabel(texto_version(actualizar.version_ytdlp()), objectName="muted")
        self.btn_actualizar = QPushButton("Actualizar yt-dlp…")
        self.btn_actualizar.setToolTip("Descarga la última versión de yt-dlp (arregla la mayoría de errores 403)")
        self.btn_actualizar.clicked.connect(self._actualizar_ytdlp)
        fila_ytdlp = QHBoxLayout()
        fila_ytdlp.addWidget(self.lbl_ytdlp, 1)
        fila_ytdlp.addWidget(self.btn_actualizar)
        mantenimiento = self._grupo("Mantenimiento")
        mantenimiento.addRow(fila_ytdlp)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        for grupo in self.grupos:
            lay.addWidget(grupo)
        lay.addSpacing(8)
        lay.addWidget(botones)

    def _grupo(self, titulo: str) -> QFormLayout:
        """Crea un QGroupBox (se añade al diálogo en orden) y devuelve su formulario."""
        grupo = QGroupBox(titulo)
        form = QFormLayout(grupo)
        form.setVerticalSpacing(10)
        self.grupos.append(grupo)
        return form

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

    def _actualizar_ytdlp(self):
        abrir_actualizar(self)

    def accept(self):
        a = self.ajustes
        a["headless"] = not self.mostrar_nav.isChecked()
        a["n_results"] = self.n_results.value()
        a["query_template"] = self.plantilla.text().strip() or DEFAULTS["query_template"]
        a["scroll_pause"] = self.scroll_pausa.value()
        a["end_rounds"] = self.fin_vueltas.value()
        a["use_cache"] = self.usar_cache.isChecked()
        a["clipboard"] = self.clip.isChecked()
        a["pause"] = self.pausa.value()
        a["auto_save"] = self.auto_guardar.isChecked()
        a["out_dir"] = self.carpeta.text().strip() or DEFAULTS["out_dir"]
        a["audio_dir"] = self.carpeta_audio.text().strip() or DEFAULTS["audio_dir"]
        super().accept()
