"""Diálogo de «Actualizar yt-dlp» (pip en un QProcess, sin bloquear la UI)."""

import sys

from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from .. import actualizar
from ..paths import CARPETA_PROYECTO


# ── Diálogo de actualización ─────────────────────────────────────────────────

def texto_version(v: str, hoy=None) -> str:
    """«yt-dlp versión 2026.08.19 (hace 64 días)»."""
    if not v:
        return "yt-dlp no está instalado"
    dias = actualizar.dias_desde_version(v, hoy)
    if dias is None:
        return f"yt-dlp versión {v}"
    cuando = "de hoy" if dias == 0 else ("de ayer" if dias == 1 else f"hace {dias} días")
    return f"yt-dlp versión {v} ({cuando})"


def ventana_principal(w: QWidget | None) -> QWidget | None:
    """La ventana principal (la que tiene `ocupado`) subiendo por los padres de `w`."""
    while w is not None:
        if hasattr(w, "ocupado"):
            return w
        w = w.parentWidget()
    return None


def abrir_actualizar(parent: QWidget | None) -> "DialogoActualizar | None":
    """
    Abre el diálogo de actualización salvo que la ventana principal esté
    convirtiendo o descargando (yt-dlp está en uso). Devuelve el diálogo o None.
    """
    ventana = ventana_principal(parent)
    if ventana is not None and ventana.ocupado:
        QMessageBox.information(parent, "Actualizar yt-dlp",
                                "Hay una conversión o descarga en curso.\n"
                                "Espera a que termine (o cancélala) para actualizar yt-dlp.")
        return None
    d = DialogoActualizar(parent)
    d.exec()
    return d


class DialogoActualizar(QDialog):
    def __init__(self, parent=None, comando: list[str] | None = None, comando_version: list[str] | None = None,
                 iniciar: bool = True):
        super().__init__(parent)
        # `comando` y `comando_version` permiten probar el diálogo sin tocar pip
        self.comando = comando or actualizar.comando_actualizar()
        self.comando_version = comando_version or actualizar.comando_version()
        self.version_antes = actualizar.version_ytdlp()
        self.version_despues = ""
        self.codigo: int | None = None    # código de salida de pip (None mientras corre)
        self.ok = False
        self._salida_version = ""
        self.setWindowTitle("Actualizar yt-dlp")
        self.setMinimumSize(560, 380)

        self.lbl_version = QLabel(f"Versión actual: {self.version_antes or 'no instalada'}")
        self.lbl_estado = QLabel("Actualizando yt-dlp…", objectName="muted")
        self.lbl_estado.setWordWrap(True)
        self.barra = QProgressBar(textVisible=False, minimum=0, maximum=0)   # indeterminada
        self.salida = QPlainTextEdit(readOnly=True, maximumBlockCount=2000)
        self.salida.setPlaceholderText("Salida de pip…")

        self.botones = QDialogButtonBox()
        self.btn_reiniciar = QPushButton("Reiniciar ahora", objectName="primary")
        self.btn_reiniciar.clicked.connect(self._reiniciar)
        self.botones.addButton(self.btn_reiniciar, QDialogButtonBox.AcceptRole)
        self.btn_reiniciar.setVisible(False)   # tras addButton, que lo vuelve a mostrar
        self.btn_cerrar = self.botones.addButton("Cerrar", QDialogButtonBox.RejectRole)
        self.btn_cerrar.setEnabled(False)
        self.btn_cerrar.clicked.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(self.lbl_version)
        lay.addWidget(self.lbl_estado)
        lay.addWidget(self.barra)
        lay.addWidget(self.salida, 1)
        lay.addWidget(self.botones)

        self.proceso = self._nuevo_proceso()
        self.proceso.readyReadStandardOutput.connect(self._leer_salida)
        self.proceso.finished.connect(self._fin_pip)
        self.proceso.errorOccurred.connect(self._error_pip)
        self.proceso_version: QProcess | None = None
        if iniciar:
            self.iniciar()

    def _nuevo_proceso(self) -> QProcess:
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PIP_DISABLE_PIP_VERSION_CHECK", "1")
        env.insert("PIP_NO_INPUT", "1")
        p.setProcessEnvironment(env)
        return p

    def iniciar(self):
        self.salida.appendPlainText("$ " + " ".join(self.comando))
        self.proceso.start(self.comando[0], self.comando[1:])

    # Proceso de pip ──────────────────────────────────────────────────────────

    def _leer_salida(self):
        texto = bytes(self.proceso.readAllStandardOutput()).decode("utf-8", "replace")
        if texto:
            self.salida.appendPlainText(texto.rstrip("\r\n").replace("\r\n", "\n"))

    def _error_pip(self, error):
        if error == QProcess.FailedToStart:
            self.salida.appendPlainText(f"No se pudo ejecutar {self.comando[0]}: {self.proceso.errorString()}")
            self._terminar(False, -1)

    def _fin_pip(self, codigo: int, estado):
        self._leer_salida()
        if self.codigo is not None:   # ya terminado (p. ej. por FailedToStart)
            return
        if estado != QProcess.NormalExit or codigo != 0:
            self._terminar(False, codigo if estado == QProcess.NormalExit else -1)
            return
        # El módulo importado en memoria no cambia: preguntar la versión a otro intérprete
        self.lbl_estado.setText("Comprobando la versión instalada…")
        self.proceso_version = self._nuevo_proceso()
        self.proceso_version.finished.connect(self._fin_version)
        self.proceso_version.errorOccurred.connect(
            lambda e: e == QProcess.FailedToStart and self._fin_version(-1, QProcess.CrashExit))
        self.proceso_version.start(self.comando_version[0], self.comando_version[1:])

    def _fin_version(self, codigo: int, estado):
        if self.codigo is not None:
            return
        if estado == QProcess.NormalExit and codigo == 0 and self.proceso_version is not None:
            salida = bytes(self.proceso_version.readAllStandardOutput()).decode("utf-8", "replace").strip()
            self.version_despues = salida.splitlines()[-1].strip() if salida else ""
        self._terminar(True, 0)

    def _terminar(self, ok: bool, codigo: int):
        self.ok, self.codigo = ok, codigo
        self.barra.setRange(0, 1)
        self.barra.setValue(1)
        self.btn_cerrar.setEnabled(True)
        nueva, antes = self.version_despues, self.version_antes
        if not ok:
            self.lbl_estado.setText(
                f"No se pudo actualizar yt-dlp (código de salida {codigo}). Revisa la salida de abajo; "
                "si no se arregla, vuelve a ejecutar instalar (instalar.bat en Windows, instalar.command en macOS)."
            )
            return
        self.lbl_version.setText(f"Versión anterior: {antes or 'no instalada'}  →  nueva: {nueva or '?'}")
        if nueva and nueva == antes:
            self.lbl_estado.setText(f"yt-dlp ya está en la última versión ({nueva}).")
            return
        self.lbl_estado.setText(f"yt-dlp actualizado a {nueva or 'la última versión'}. "
                                "Reinicia la app para usar la nueva versión.")
        self.btn_reiniciar.setVisible(True)
        self.btn_reiniciar.setDefault(True)

    # Cierre y reinicio ───────────────────────────────────────────────────────

    def reject(self):
        if self.codigo is None and self.proceso.state() != QProcess.NotRunning:
            r = QMessageBox.question(self, "Actualizar yt-dlp", "La actualización sigue en curso. ¿Detenerla?")
            if r != QMessageBox.Yes:
                return
            self.proceso.kill()
            self.proceso.waitForFinished(3000)
        super().reject()

    def closeEvent(self, event):
        if self.codigo is None and self.proceso.state() != QProcess.NotRunning:
            event.ignore()
            self.reject()
            return
        super().closeEvent(event)

    def _reiniciar(self):
        ventana = ventana_principal(self.parentWidget())
        self.accept()
        # Cerrar los diálogos abiertos (p. ej. Ajustes) y la ventana; su closeEvent puede negarse
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w is not self and w.isVisible():
                w.reject()
        if ventana is not None and not ventana.close():
            return
        QProcess.startDetached(sys.executable, ["-m", "spotyurl.gui"], str(CARPETA_PROYECTO))
