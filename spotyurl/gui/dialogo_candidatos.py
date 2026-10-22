"""Diálogo «Elegir otra versión»: lista los vídeos candidatos de una canción."""

import html

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..models import Status, Track, fmt_duration
from .tema import colores_estado
from .workers import CandidatosWorker

# Hilos de búsqueda de diálogos ya cerrados: se guardan hasta que terminan
# (destruir un QThread en marcha cierra la aplicación)
_HILOS_HUERFANOS: set[CandidatosWorker] = set()


def esperar_busquedas(ms: int = 3000):
    """Al salir de la app: cancela y espera las búsquedas de candidatos aún en marcha."""
    for w in list(_HILOS_HUERFANOS):
        w.cancel.set()
        w.wait(ms)


def diferencia_duracion(video_s: int | None, spotify_s: int | None) -> str:
    """'+0:05', '−0:12' o '=' (vacío si falta alguna duración)."""
    if video_s is None or spotify_s is None:
        return ""
    diff = video_s - spotify_s
    if diff == 0:
        return "="
    return f"{'+' if diff > 0 else '−'}{fmt_duration(abs(diff))}"


class DialogoCandidatos(QDialog):
    """
    Muestra los candidatos de `track` (los busca en un hilo si no hay ninguno).
    Al aceptar, `elegido` es el youtube.Candidate escogido; `candidatos` guarda
    la lista mostrada (para conservarla en la fila aunque se cancele).
    Con `revision=True` añade «Saltar» (resultado SALTAR) para revisar dudosas en cadena.
    """

    SALTAR = 2
    COLUMNAS = ["Vídeo", "Canal", "Duración", "Puntuación"]

    def __init__(self, track: Track, opts: dict, tema: str = "dark", revision: bool = False, parent=None):
        super().__init__(parent)
        self.track, self.opts = track, opts
        self.colores = colores_estado(tema)
        self.candidatos: list = list(track.candidates)
        self.elegido = None
        self.worker: CandidatosWorker | None = None
        self.setWindowTitle("Elegir otra versión")
        self.resize(760, 380)

        duracion = f" · {fmt_duration(track.duration_s)} en Spotify" if track.duration_s else ""
        cabecera = QLabel(f"<b>{html.escape(track.label)}</b>{html.escape(duracion)}", wordWrap=True)
        self.lbl_estado = QLabel(objectName="muted", wordWrap=True)

        self.tabla = QTableWidget(0, len(self.COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(self.COLUMNAS)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.setWordWrap(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(32)
        hh = self.tabla.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        self.tabla.setColumnWidth(1, 170)
        self.tabla.setColumnWidth(2, 120)
        self.tabla.setColumnWidth(3, 90)
        self.tabla.doubleClicked.connect(lambda _i: self._usar())
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)

        self.btn_escuchar = QPushButton("▶  Escuchar")
        self.btn_escuchar.setToolTip("Abre el vídeo en el navegador")
        self.btn_escuchar.clicked.connect(self._escuchar)
        buscar = QPushButton("Buscar a mano…")
        buscar.setToolTip("Abre la búsqueda en YouTube (luego pega el enlace en la celda)")
        buscar.clicked.connect(self._buscar_a_mano)
        self.btn_usar = QPushButton("Usar esta versión", objectName="primary")
        self.btn_usar.setDefault(True)
        self.btn_usar.clicked.connect(self._usar)
        cancelar = QPushButton("Cerrar" if not revision else "Terminar revisión")
        cancelar.clicked.connect(self.reject)

        botones = QHBoxLayout()
        botones.addWidget(self.btn_escuchar)
        botones.addWidget(buscar)
        botones.addStretch(1)
        botones.addWidget(cancelar)
        if revision:
            saltar = QPushButton("Saltar")
            saltar.setToolTip("Dejarla como dudosa y pasar a la siguiente")
            saltar.clicked.connect(lambda: self.done(self.SALTAR))
            botones.addWidget(saltar)
        botones.addWidget(self.btn_usar)

        lay = QVBoxLayout(self)
        lay.addWidget(cabecera)
        lay.addWidget(self.lbl_estado)
        lay.addWidget(self.tabla, 1)
        lay.addLayout(botones)

        if self.candidatos:
            self._mostrar(self.candidatos)
        else:
            self._buscar()

    # Búsqueda ────────────────────────────────────────────────────────────────

    def _buscar(self):
        self.lbl_estado.setText("Buscando en YouTube…")
        self.worker = CandidatosWorker(self.opts, self.track)
        self.worker.listos.connect(self._on_listos)
        self.worker.failed.connect(self._on_error)
        self.worker.start()
        self._actualizar_botones()

    def _on_listos(self, cands: list):
        self.candidatos = list(cands)
        self._mostrar(self.candidatos)

    def _on_error(self, msg: str):
        self.lbl_estado.setText(f"No se pudo buscar en YouTube: {msg}")

    def buscando(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    # Tabla ───────────────────────────────────────────────────────────────────

    def _mostrar(self, cands: list):
        self.tabla.setRowCount(0)
        if not cands:
            self.lbl_estado.setText("YouTube no devolvió ningún vídeo. Prueba «Buscar a mano…».")
            self._actualizar_botones()
            return
        actual = -1
        negrita = QFont(self.tabla.font())
        negrita.setBold(True)
        for i, c in enumerate(cands):
            es_actual = c.url == self.track.youtube_url
            if es_actual:
                actual = i
            dif = diferencia_duracion(c.duration_s, self.track.duration_s)
            duracion = fmt_duration(c.duration_s) + (f"  ({dif})" if dif and dif != "=" else "")
            celdas = [("●  " if es_actual else "") + c.title, c.channel, duracion, f"{c.score:.2f}"]
            for col, texto in enumerate(celdas):
                item = QTableWidgetItem(texto)
                item.setToolTip(c.title if col == 0 else c.url if col == 1 else "")
                if es_actual:
                    item.setFont(negrita)
                if col in (2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setRowCount(max(self.tabla.rowCount(), i + 1))
                self.tabla.setItem(i, col, item)
            # Color de la diferencia de duración: verde si cuadra, ámbar/rojo si no
            if c.duration_s is not None and self.track.duration_s is not None:
                diff = abs(c.duration_s - self.track.duration_s)
                estado = Status.OK if diff <= 3 else Status.DOUBTFUL if diff <= 15 else Status.FAILED
                self.tabla.item(i, 2).setForeground(QColor(self.colores[estado]))
                self.tabla.item(i, 2).setToolTip(f"Diferencia con Spotify: {dif}")
        texto = f"{len(cands)} vídeos encontrados."
        texto += " El actual está marcado con ●." if actual >= 0 else ""
        self.lbl_estado.setText(texto + " Doble clic para usar uno.")
        self.tabla.selectRow(actual if actual >= 0 else 0)
        self.tabla.setFocus()
        self._actualizar_botones()

    def _seleccionado(self):
        filas = self.tabla.selectionModel().selectedRows()
        if not filas or filas[0].row() >= len(self.candidatos):
            return None
        return self.candidatos[filas[0].row()]

    def _actualizar_botones(self):
        hay = self._seleccionado() is not None
        self.btn_escuchar.setEnabled(hay)
        self.btn_usar.setEnabled(hay)

    # Acciones ────────────────────────────────────────────────────────────────

    def _escuchar(self):
        c = self._seleccionado()
        if c:
            QDesktopServices.openUrl(QUrl(c.url))

    def _buscar_a_mano(self):
        consulta = QUrl.toPercentEncoding(self.track.label).data().decode()
        QDesktopServices.openUrl(QUrl(f"https://www.youtube.com/results?search_query={consulta}"))

    def _usar(self):
        c = self._seleccionado()
        if c:
            self.elegido = c
            self.accept()

    def done(self, r):
        if self.buscando():
            # No se puede destruir el hilo en marcha: se cancela y se guarda hasta que acabe
            w = self.worker
            w.cancel.set()
            for sig in (w.listos, w.failed):
                sig.disconnect()
            _HILOS_HUERFANOS.add(w)
            w.finished.connect(lambda: _HILOS_HUERFANOS.discard(w))
        super().done(r)
