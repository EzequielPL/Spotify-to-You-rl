"""
Interfaz gráfica (PySide6).

    python -m spotyurl.gui

Todo el trabajo pesado (Playwright + yt-dlp) corre en un único QThread que
habla con la UI mediante señales; la UI nunca toca Playwright.
"""


import dataclasses
import re
import sys
import threading
import traceback
from pathlib import Path
from string import Template

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QSettings, QSortFilterProxyModel, Qt,
    QThread, QUrl, Signal,
)
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
    QAbstractSpinBox, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSpinBox,
    QStackedWidget, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from . import __version__
from .export import FORMATOS, default_name, export, to_txt
from .models import Status, Track, app_data_dir, fmt_duration
from .spotify import ScrapeConfig, SpotifyError, fetch_tracks, parse_source, parse_text_list

CARPETA_PROYECTO = Path(__file__).resolve().parent.parent
CACHE_PATH = app_data_dir() / "search_cache.json"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.svg"
RE_YOUTUBE = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/)|youtu\.be/)([\w-]{11})")

COLOR_ESTADO = {
    Status.PENDING: "#8a8f98",
    Status.SEARCHING: "#3b82f6",
    Status.OK: "#1db954",
    Status.DOUBTFUL: "#f5a524",
    Status.FAILED: "#f04461",
    Status.MANUAL: "#a970ff",
}


# ── Ajustes persistentes ─────────────────────────────────────────────────────

DEFAULTS = {
    "clipboard": True,
    "pause": 1.0,
    "headless": True,
    "n_results": 6,
    "query_template": "{artist} - {title}",
    "scroll_pause": 0.7,
    "end_rounds": 8,
    "use_cache": True,
    "auto_save": True,
    "out_dir": str(CARPETA_PROYECTO),
    "theme": "dark",
}


class Ajustes:
    def __init__(self):
        self._s = QSettings("spotyurl", "Spotify to You-rl")

    def __getitem__(self, key):
        default = DEFAULTS[key]
        value = self._s.value(key, default)
        # QSettings en Windows devuelve strings: convertir al tipo del default
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        if isinstance(default, (int, float)):
            try:
                return type(default)(value)
            except (TypeError, ValueError):
                return default
        return value

    def __setitem__(self, key, value):
        self._s.setValue(key, value)

    def snapshot(self) -> dict:
        return {k: self[k] for k in DEFAULTS}


# ── Modelo de la tabla ───────────────────────────────────────────────────────

ROL_ESTADO = Qt.UserRole + 1


class TrackTableModel(QAbstractTableModel):
    COLUMNAS = ["#", "Título", "Artista", "Duración", "Estado", "Enlace de YouTube"]
    COL_ESTADO, COL_ENLACE = 4, 5

    def __init__(self):
        super().__init__()
        self.tracks: list[Track] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.tracks)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNAS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNAS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        t = self.tracks[index.row()]
        col = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            return [
                index.row() + 1, t.title, t.artist, fmt_duration(t.duration_s),
                f"●  {t.status.value}", t.youtube_url,
            ][col]
        if role == Qt.ForegroundRole and col == self.COL_ESTADO:
            return QColor(COLOR_ESTADO[t.status])
        if role == Qt.ToolTipRole:
            if col == self.COL_ENLACE and t.youtube_title:
                score = "" if t.score is None else f"  ·  puntuación {t.score:.2f}"
                return f"{t.youtube_title}{score}\nDoble clic para pegar otro enlace"
            if col == self.COL_ENLACE:
                return "Doble clic para pegar un enlace de YouTube"
            if col == 1 and t.album:
                return f"Álbum: {t.album}"
        if role == Qt.TextAlignmentRole and col in (0, 3):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == ROL_ESTADO:
            return t.status
        return None

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemIsEditable if index.column() == self.COL_ENLACE else f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or index.column() != self.COL_ENLACE:
            return False
        t = self.tracks[index.row()]
        value = str(value).strip()
        if not value:
            t.youtube_url, t.youtube_title, t.score, t.status = "", "", None, Status.FAILED
        else:
            m = RE_YOUTUBE.search(value)
            if not m:
                return False
            t.youtube_url = f"https://www.youtube.com/watch?v={m.group(1)}"
            t.youtube_title, t.score, t.status = "", None, Status.MANUAL
        self._row_changed(index.row())
        return True

    # API usada por la ventana
    def _row_changed(self, row):
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))

    def set_tracks(self, tracks: list[Track]):
        self.beginResetModel()
        self.tracks = list(tracks)
        self.endResetModel()

    def add_track(self, t: Track):
        n = len(self.tracks)
        self.beginInsertRows(QModelIndex(), n, n)
        self.tracks.append(t)
        self.endInsertRows()

    def update_track(self, row: int, t: Track):
        if 0 <= row < len(self.tracks):
            self.tracks[row] = t
            self._row_changed(row)

    def remove_rows(self, rows: list[int]):
        for row in sorted(rows, reverse=True):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.tracks[row]
            self.endRemoveRows()

    def counts(self) -> dict[Status, int]:
        c = {s: 0 for s in Status}
        for t in self.tracks:
            c[t.status] += 1
        return c


class FiltroTracks(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.texto = ""
        self.estados: set[Status] | None = None

    def set_filtro(self, texto: str, estados: set[Status] | None):
        self.texto, self.estados = texto.lower().strip(), estados
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        t = self.sourceModel().tracks[row]
        if self.estados is not None and t.status not in self.estados:
            return False
        return not self.texto or self.texto in f"{t.title} {t.artist} {t.album}".lower()


# ── Hilo de trabajo ──────────────────────────────────────────────────────────

class Worker(QThread):
    tracks_reset = Signal(list)
    track_added = Signal(object)
    track_updated = Signal(int, object)
    phase = Signal(str, int)
    progress = Signal(int)
    log = Signal(str)
    copy_request = Signal(str)
    failed = Signal(str)

    def __init__(self, opts: dict, url: str | None = None,
                 items: list[tuple[int, Track]] | None = None, use_cache: bool = True):
        super().__init__()
        self.opts, self.url, self.items, self.use_cache = opts, url, items or [], use_cache
        self.cancel = threading.Event()

    def run(self):
        try:
            if self.url:
                self._extraer()
            if not self.cancel.is_set():
                self._buscar()
        except SpotifyError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.log.emit(traceback.format_exc())
            self.failed.emit(f"Error inesperado: {e}")

    def _extraer(self):
        self.phase.emit("Extrayendo canciones de Spotify…", 0)
        cfg = ScrapeConfig(
            headless=self.opts["headless"],
            scroll_pause=self.opts["scroll_pause"],
            end_rounds=self.opts["end_rounds"],
        )
        tracks = fetch_tracks(
            self.url, cfg,
            on_track=lambda t: self.track_added.emit(dataclasses.replace(t)),
            on_log=self.log.emit,
            cancel=self.cancel,
        )
        self.tracks_reset.emit([dataclasses.replace(t) for t in tracks])
        self.items = list(enumerate(tracks))
        self.log.emit(f"{len(tracks)} canciones extraídas.")

    def _buscar(self):
        from .youtube import YouTubeMatcher

        if not self.items:
            return
        matcher = YouTubeMatcher(
            n_results=self.opts["n_results"],
            query_template=self.opts["query_template"],
            cache_path=CACHE_PATH if self.opts["use_cache"] else None,
        )
        self.phase.emit("Buscando en YouTube…", len(self.items))
        try:
            for k, (row, t) in enumerate(self.items, 1):
                if self.cancel.is_set():
                    break
                t = dataclasses.replace(t, status=Status.SEARCHING)
                self.track_updated.emit(row, dataclasses.replace(t))
                try:
                    matcher.match(t, self.cancel, use_cache=self.use_cache and self.opts["use_cache"])
                except Exception as e:
                    t.status = Status.FAILED
                    self.log.emit(f"Error YouTube en «{t.label}»: {e}")
                if self.cancel.is_set() and t.status == Status.SEARCHING:
                    t.status = Status.PENDING
                self.track_updated.emit(row, dataclasses.replace(t))
                self.progress.emit(k)
                if t.youtube_url and self.opts["clipboard"]:
                    self.copy_request.emit(t.youtube_url)
                    if k < len(self.items):
                        self.cancel.wait(self.opts["pause"])
        finally:
            matcher.save_cache()


# ── Tema ─────────────────────────────────────────────────────────────────────

PALETAS = {
    "dark": dict(bg="#0f1115", card="#171a21", alt="#1b1f27", input="#20242d", border="#2a2f3a",
                 text="#e8eaed", muted="#8a8f98", btn="#232833", btn_hover="#2c3240",
                 sel="#25402f", accent="#1db954", accent_hover="#1ed760", danger="#f04461"),
    "light": dict(bg="#f4f5f7", card="#ffffff", alt="#f8f9fb", input="#f1f3f5", border="#dde1e6",
                  text="#15181d", muted="#6b7280", btn="#ffffff", btn_hover="#eef0f3",
                  sel="#d9f5e3", accent="#1db954", accent_hover="#17a34a", danger="#e11d48"),
}

QSS = Template("""
* { font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; }
QMainWindow, QDialog, QWidget#root { background: $bg; }
QWidget { color: $text; }
QToolTip { background: $card; color: $text; border: 1px solid $border; padding: 6px; }
QFrame#card { background: $card; border: 1px solid $border; border-radius: 12px; }
QLabel#title { font-size: 17pt; font-weight: 600; }
QLabel#subtitle, QLabel#muted { color: $muted; }
QLabel#empty { color: $muted; font-size: 11pt; }
QLabel#chip { background: $input; border-radius: 11px; padding: 3px 11px; }

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $input; border: 1px solid $border; border-radius: 8px; padding: 6px 10px;
    selection-background-color: $accent; selection-color: #0b0b0b;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QAbstractSpinBox QLineEdit { background: transparent; border: none; padding: 0 0 0 10px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    subcontrol-origin: border; width: 0px; border: none;   /* sin flechas: rueda o teclado */
}
QLineEdit[state="invalid"] { border-color: $danger; }
QLineEdit[state="valid"] { border-color: $accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $card; border: 1px solid $border; selection-background-color: $sel; }

QPushButton, QToolButton {
    background: $btn; border: 1px solid $border; border-radius: 8px; padding: 7px 14px;
}
QPushButton:hover, QToolButton:hover { background: $btn_hover; }
QPushButton:disabled, QToolButton:disabled { color: $muted; }
QToolButton::menu-indicator { image: none; }
QPushButton#primary { background: $accent; color: #0b0b0b; border: none; font-weight: 600; padding: 9px 26px; }
QPushButton#primary:hover { background: $accent_hover; }
QPushButton#primary:disabled { background: $btn; color: $muted; }
QPushButton#primary[running="true"] { background: $danger; color: white; }
QPushButton#ghost { background: transparent; border: none; padding: 6px 10px; }
QPushButton#ghost:hover { background: $btn_hover; }
QPushButton#segment { border-radius: 0; padding: 6px 16px; background: $input; }
QPushButton#segment[pos="left"] { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#segment[pos="right"] { border-top-right-radius: 8px; border-bottom-right-radius: 8px; border-left: none; }
QPushButton#segment:checked { background: $accent; color: #0b0b0b; border-color: $accent; }

QTableView {
    background: $card; alternate-background-color: $alt; border: 1px solid $border; border-radius: 12px;
    gridline-color: transparent; selection-background-color: $sel; selection-color: $text; outline: 0;
}
QTableView::item { padding: 4px 8px; border: none; }
QHeaderView::section {
    background: $card; color: $muted; border: none; border-bottom: 1px solid $border;
    padding: 8px; font-weight: 600;
}
QTableCornerButton::section { background: $card; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px; }
QScrollBar::handle:vertical { background: $border; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar:horizontal { height: 0; }

QProgressBar { background: $input; border: none; border-radius: 4px; max-height: 8px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid $border; background: $input; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QMenu { background: $card; border: 1px solid $border; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: $sel; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }
""")


def aplicar_tema(app: QApplication, tema: str):
    app.setStyleSheet(QSS.substitute(PALETAS.get(tema, PALETAS["dark"])))


def repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)


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
        examinar = QPushButton("Examinar…")
        examinar.clicked.connect(self._elegir_carpeta)
        fila_carpeta = QHBoxLayout()
        fila_carpeta.addWidget(self.carpeta, 1)
        fila_carpeta.addWidget(examinar)
        vaciar = QPushButton("Vaciar caché de búsquedas")
        vaciar.clicked.connect(self._vaciar_cache)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("Carpeta de salida", fila_carpeta)
        form.addRow("", self.auto_guardar)
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

    def _elegir_carpeta(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de salida", self.carpeta.text())
        if d:
            self.carpeta.setText(d)

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
        super().accept()


# ── Ventana principal ────────────────────────────────────────────────────────

FILTROS_ESTADO = [
    ("Todas", None),
    ("Encontradas", {Status.OK, Status.MANUAL}),
    ("Dudoso", {Status.DOUBTFUL}),
    ("Sin match", {Status.FAILED}),
    ("Pendientes", {Status.PENDING, Status.SEARCHING}),
]


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ajustes = Ajustes()
        self.worker: Worker | None = None
        self.ultimo_archivo: Path | None = None
        self.setWindowTitle("Spotify to You-rl")
        self.resize(1120, 760)
        self.setMinimumSize(820, 560)

        self.model = TrackTableModel()
        self.proxy = FiltroTracks()
        self.proxy.setSourceModel(self.model)

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        lay.addLayout(self._cabecera())
        lay.addWidget(self._entrada())
        lay.addLayout(self._estado())
        lay.addLayout(self._filtros())
        lay.addWidget(self._tabla(), 1)
        lay.addLayout(self._pie())
        self.log_view = QPlainTextEdit(readOnly=True, maximumBlockCount=2000)
        self.log_view.setFixedHeight(140)
        self.log_view.setVisible(False)
        lay.addWidget(self.log_view)

        for sig in (self.model.dataChanged, self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset):
            sig.connect(self._refrescar)
        self._validar_entrada()
        self._refrescar()

    # Construcción ────────────────────────────────────────────────────────────

    def _cabecera(self):
        titulo = QLabel("Spotify → YouTube", objectName="title")
        sub = QLabel("Convierte playlists y álbumes de Spotify en enlaces de YouTube", objectName="subtitle")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(titulo)
        col.addWidget(sub)

        self.btn_tema = QPushButton(objectName="ghost")
        self.btn_tema.setToolTip("Cambiar tema claro/oscuro")
        self.btn_tema.clicked.connect(self._cambiar_tema)
        self._texto_tema()
        btn_ajustes = QPushButton("⚙  Ajustes", objectName="ghost")
        btn_ajustes.clicked.connect(self._abrir_ajustes)

        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON_PATH)).pixmap(44, 44))

        h = QHBoxLayout()
        h.setSpacing(12)
        h.addWidget(logo)
        h.addLayout(col, 1)
        h.addWidget(self.btn_tema)
        h.addWidget(btn_ajustes)
        return h

    def _entrada(self):
        c = card()
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        self.seg_enlace = QPushButton("Enlace de Spotify", objectName="segment", checkable=True, checked=True)
        self.seg_texto = QPushButton("Lista de texto", objectName="segment", checkable=True)
        self.seg_enlace.setProperty("pos", "left")
        self.seg_texto.setProperty("pos", "right")
        grupo = QButtonGroup(self)
        grupo.setExclusive(True)
        for i, b in enumerate((self.seg_enlace, self.seg_texto)):
            grupo.addButton(b, i)
        grupo.idClicked.connect(self._cambiar_modo)
        segs = QHBoxLayout()
        segs.setSpacing(0)
        segs.addWidget(self.seg_enlace)
        segs.addWidget(self.seg_texto)
        segs.addStretch(1)
        self.lbl_ayuda = QLabel(objectName="muted")
        segs.addWidget(self.lbl_ayuda)
        v.addLayout(segs)

        self.url = QLineEdit(placeholderText="https://open.spotify.com/playlist/…  o  /album/…")
        self.url.setClearButtonEnabled(True)
        self.url.textChanged.connect(self._validar_entrada)
        self.url.returnPressed.connect(self._convertir)
        pegar = QPushButton("Pegar")
        pegar.clicked.connect(lambda: self.url.setText(QGuiApplication.clipboard().text().strip()))
        pagina_url = QWidget()
        hu = QHBoxLayout(pagina_url)
        hu.setContentsMargins(0, 0, 0, 0)
        hu.addWidget(self.url, 1)
        hu.addWidget(pegar)

        self.texto = QPlainTextEdit(placeholderText="Una canción por línea:\nBruno Mars - Locked Out of Heaven\nRosalía - Despechá")
        self.texto.setFixedHeight(110)
        self.texto.textChanged.connect(self._validar_entrada)

        self.paginas_entrada = [pagina_url, self.texto]
        self.modo = 0

        self.btn_convertir = QPushButton("Convertir", objectName="primary")
        self.btn_convertir.setCursor(Qt.PointingHandCursor)
        self.btn_convertir.clicked.connect(self._convertir)
        h = QHBoxLayout()
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        for pagina in self.paginas_entrada:
            col.addWidget(pagina)
        h.addLayout(col, 1)
        h.addWidget(self.btn_convertir, 0, Qt.AlignTop)
        v.addLayout(h)
        c.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._cambiar_modo(0)
        return c

    def _estado(self):
        self.lbl_fase = QLabel("Listo", objectName="muted")
        self.btn_archivo = QPushButton("Mostrar archivo", objectName="ghost")
        self.btn_archivo.setVisible(False)
        self.btn_archivo.clicked.connect(self._mostrar_archivo)
        self.barra = QProgressBar(textVisible=False)
        self.barra.setVisible(False)
        self.chips = {
            Status.OK: QLabel(objectName="chip"),
            Status.DOUBTFUL: QLabel(objectName="chip"),
            Status.FAILED: QLabel(objectName="chip"),
        }
        h = QHBoxLayout()
        h.addWidget(self.lbl_fase)
        h.addWidget(self.btn_archivo)
        h.addWidget(self.barra, 1)
        h.addStretch(0)
        for chip in self.chips.values():
            h.addWidget(chip)
        return h

    def _filtros(self):
        self.filtro_texto = QLineEdit(placeholderText="Filtrar por título, artista o álbum…")
        self.filtro_texto.setClearButtonEnabled(True)
        self.filtro_estado = QComboBox()
        for nombre, _ in FILTROS_ESTADO:
            self.filtro_estado.addItem(nombre)
        self.filtro_texto.textChanged.connect(self._aplicar_filtro)
        self.filtro_estado.currentIndexChanged.connect(self._aplicar_filtro)
        h = QHBoxLayout()
        h.addWidget(self.filtro_texto, 1)
        h.addWidget(self.filtro_estado)
        return h

    def _tabla(self):
        self.tabla = QTableView()
        self.tabla.setModel(self.proxy)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.tabla.setShowGrid(False)
        self.tabla.setWordWrap(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(34)
        hh = self.tabla.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        for col, ancho in enumerate((48, 300, 220, 80, 120)):
            self.tabla.setColumnWidth(col, ancho)
        hh.setStretchLastSection(True)
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)
        self.tabla.doubleClicked.connect(self._doble_clic)

        copiar = QAction(self.tabla, shortcut=QKeySequence(QKeySequence.Copy), shortcutContext=Qt.WidgetShortcut)
        copiar.triggered.connect(self._copiar_seleccion)
        borrar = QAction(self.tabla, shortcut=QKeySequence(QKeySequence.Delete), shortcutContext=Qt.WidgetShortcut)
        borrar.triggered.connect(self._quitar_seleccion)
        self.tabla.addActions([copiar, borrar])

        self.vacio = QLabel(
            "Pega el enlace de una playlist o álbum público de Spotify y pulsa <b>Convertir</b>.<br>"
            "También puedes pegar una lista de canciones en «Lista de texto».",
            objectName="empty", alignment=Qt.AlignCenter,
        )
        self.stack_tabla = QStackedWidget()
        self.stack_tabla.addWidget(self.vacio)
        self.stack_tabla.addWidget(self.tabla)
        return self.stack_tabla

    def _pie(self):
        self.chk_clip = QCheckBox("Copiar cada enlace al portapapeles")
        self.chk_clip.setToolTip("Útil con MediaHuman u otros gestores que detectan enlaces del portapapeles")
        self.chk_clip.setChecked(self.ajustes["clipboard"])
        self.chk_clip.toggled.connect(lambda v: self.ajustes.__setitem__("clipboard", v))
        self.pausa = QDoubleSpinBox(minimum=0, maximum=10, singleStep=0.5, value=self.ajustes["pause"], suffix=" s")
        self.pausa.setToolTip("Pausa entre copias al portapapeles")
        self.pausa.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.pausa.valueChanged.connect(lambda v: self.ajustes.__setitem__("pause", v))
        self.chk_clip.toggled.connect(self.pausa.setEnabled)
        self.pausa.setEnabled(self.chk_clip.isChecked())

        self.btn_reintentar = QPushButton("↻  Reintentar fallidas")
        self.btn_reintentar.clicked.connect(self._reintentar_fallidas)
        self.btn_copiar = QPushButton("Copiar todo")
        self.btn_copiar.clicked.connect(self._copiar_todo)
        self.btn_exportar = QToolButton(text="Exportar  ▾", popupMode=QToolButton.InstantPopup)
        menu = QMenu(self.btn_exportar)
        for ext, desc in FORMATOS.items():
            menu.addAction(desc, lambda e=ext: self._exportar(e))
        self.btn_exportar.setMenu(menu)
        self.btn_log = QPushButton("Log", objectName="ghost", checkable=True)
        self.btn_log.toggled.connect(lambda v: self.log_view.setVisible(v))

        h = QHBoxLayout()
        h.addWidget(self.chk_clip)
        h.addWidget(self.pausa)
        h.addStretch(1)
        h.addWidget(self.btn_log)
        h.addWidget(self.btn_reintentar)
        h.addWidget(self.btn_copiar)
        h.addWidget(self.btn_exportar)
        return h

    # Estado de la UI ─────────────────────────────────────────────────────────

    @property
    def ocupado(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _cambiar_modo(self, idx: int):
        self.modo = idx
        for i, pagina in enumerate(self.paginas_entrada):
            pagina.setVisible(i == idx)
        self._validar_entrada()

    def _validar_entrada(self):
        if self.modo == 0:
            txt = self.url.text().strip()
            src = parse_source(txt) if txt else None
            self.url.setProperty("state", "" if not txt else "valid" if src else "invalid")
            repolish(self.url)
            self.lbl_ayuda.setText(
                "" if not txt else f"{'Playlist' if src.kind == 'playlist' else 'Álbum'} detectado" if src
                else "Enlace no reconocido"
            )
            ok = src is not None
        else:
            n = len(parse_text_list(self.texto.toPlainText()))
            self.lbl_ayuda.setText(f"{n} canciones" if n else "")
            ok = n > 0
        if not self.ocupado:
            self.btn_convertir.setEnabled(ok)

    def _refrescar(self):
        c = self.model.counts()
        self.chips[Status.OK].setText(f"<span style='color:{COLOR_ESTADO[Status.OK]}'>●</span>  {c[Status.OK] + c[Status.MANUAL]} encontradas")
        self.chips[Status.DOUBTFUL].setText(f"<span style='color:{COLOR_ESTADO[Status.DOUBTFUL]}'>●</span>  {c[Status.DOUBTFUL]} dudosas")
        self.chips[Status.FAILED].setText(f"<span style='color:{COLOR_ESTADO[Status.FAILED]}'>●</span>  {c[Status.FAILED]} sin match")
        hay = bool(self.model.tracks)
        self.stack_tabla.setCurrentIndex(1 if hay else 0)
        con_enlace = any(t.youtube_url for t in self.model.tracks)
        self.btn_copiar.setEnabled(con_enlace)
        self.btn_exportar.setEnabled(hay)
        self.btn_reintentar.setEnabled(not self.ocupado and c[Status.FAILED] + c[Status.PENDING] > 0
                                       and c[Status.PENDING] != len(self.model.tracks))

    def _set_ocupado(self, ocupado: bool):
        self.btn_convertir.setText("Cancelar" if ocupado else "Convertir")
        self.btn_convertir.setProperty("running", ocupado)
        repolish(self.btn_convertir)
        self.btn_convertir.setEnabled(True)
        for w in (self.seg_enlace, self.seg_texto, self.url, self.texto):
            w.setEnabled(not ocupado)
        self.barra.setVisible(ocupado)
        if not ocupado:
            self._validar_entrada()
        self._refrescar()

    def _aplicar_filtro(self):
        self.proxy.set_filtro(self.filtro_texto.text(), FILTROS_ESTADO[self.filtro_estado.currentIndex()][1])

    def _log(self, msg: str):
        self.log_view.appendPlainText(msg.rstrip())

    # Acciones ────────────────────────────────────────────────────────────────

    def _convertir(self):
        if self.ocupado:
            self.worker.cancel.set()
            self.btn_convertir.setEnabled(False)
            self.lbl_fase.setText("Cancelando…")
            return
        if not self.btn_convertir.isEnabled():
            return
        self.btn_archivo.setVisible(False)
        if self.modo == 0:
            self.model.set_tracks([])
            self._lanzar(Worker(self.ajustes.snapshot(), url=self.url.text().strip()))
        else:
            tracks = parse_text_list(self.texto.toPlainText())
            self.model.set_tracks(tracks)
            self._lanzar(Worker(self.ajustes.snapshot(), items=[(i, dataclasses.replace(t)) for i, t in enumerate(tracks)]))

    def _buscar_filas(self, rows: list[int], use_cache: bool):
        if self.ocupado or not rows:
            return
        items = [(r, dataclasses.replace(self.model.tracks[r])) for r in sorted(rows)]
        self._lanzar(Worker(self.ajustes.snapshot(), items=items, use_cache=use_cache), guardar=False)

    def _lanzar(self, w: Worker, guardar: bool = True):
        self.worker = w
        w.tracks_reset.connect(self.model.set_tracks)
        w.track_added.connect(self.model.add_track)
        w.track_updated.connect(self.model.update_track)
        w.phase.connect(self._on_fase)
        w.progress.connect(self._on_progreso)
        w.log.connect(self._log)
        w.copy_request.connect(lambda url: QGuiApplication.clipboard().setText(url))
        w.failed.connect(self._on_error)
        w.finished.connect(lambda: self._on_fin(w, guardar))
        w.start()
        self._set_ocupado(True)

    def _on_fase(self, texto: str, total: int):
        self._fase, self._total = texto, total
        self.barra.setRange(0, total)
        self.barra.setValue(0)
        self.lbl_fase.setText(texto if not total else f"{texto} 0/{total}")
        self._log(f"── {texto}")

    def _on_progreso(self, k: int):
        self.barra.setValue(k)
        self.lbl_fase.setText(f"{self._fase} {k}/{self._total}")

    def _on_error(self, msg: str):
        self._log(msg)
        QMessageBox.warning(self, "No se pudo completar", msg)

    def _on_fin(self, w: Worker, guardar: bool):
        cancelado = w.cancel.is_set()
        self.worker = None
        w.deleteLater()
        self._set_ocupado(False)
        tracks = self.model.tracks
        n_links = sum(bool(t.youtube_url) for t in tracks)
        estado = "Cancelado" if cancelado else "Listo"
        self.lbl_fase.setText(f"{estado}: {n_links} de {len(tracks)} canciones con enlace")
        if guardar and n_links and w.opts["auto_save"] and not cancelado:
            carpeta = Path(self.ajustes["out_dir"])
            try:
                carpeta.mkdir(parents=True, exist_ok=True)
                self.ultimo_archivo = carpeta / default_name("txt")
                to_txt(tracks, self.ultimo_archivo)
                self._log(f"Guardado: {self.ultimo_archivo}")
                self.lbl_fase.setText(self.lbl_fase.text() + f"  ·  {self.ultimo_archivo.name}")
                self.btn_archivo.setVisible(True)
            except OSError as e:
                self._log(f"No se pudo guardar el .txt: {e}")

    def _filas_seleccionadas(self) -> list[int]:
        return sorted({self.proxy.mapToSource(i).row() for i in self.tabla.selectionModel().selectedRows()})

    def _menu_contextual(self, pos):
        rows = self._filas_seleccionadas()
        if not rows:
            return
        t = self.model.tracks[rows[0]]
        menu = QMenu(self)
        a_abrir = menu.addAction("Abrir en YouTube", lambda: self._abrir(rows))
        a_abrir.setEnabled(any(self.model.tracks[r].youtube_url for r in rows))
        menu.addAction("Copiar enlace", self._copiar_seleccion).setEnabled(a_abrir.isEnabled())
        menu.addAction("Buscar a mano en YouTube…", lambda: QDesktopServices.openUrl(
            QUrl(f"https://www.youtube.com/results?search_query={QUrl.toPercentEncoding(t.label).data().decode()}")))
        menu.addSeparator()
        menu.addAction("Reintentar búsqueda", lambda: self._buscar_filas(rows, use_cache=False)).setEnabled(not self.ocupado)
        menu.addAction("Pegar otro enlace…", lambda: self.tabla.edit(
            self.proxy.mapFromSource(self.model.index(rows[0], TrackTableModel.COL_ENLACE))))
        menu.addSeparator()
        menu.addAction("Quitar de la lista", self._quitar_seleccion).setEnabled(not self.ocupado)
        menu.exec(self.tabla.viewport().mapToGlobal(pos))

    def _doble_clic(self, index):
        if index.column() != TrackTableModel.COL_ENLACE:
            self._abrir([self.proxy.mapToSource(index).row()])

    def _abrir(self, rows):
        for r in rows[:10]:
            if self.model.tracks[r].youtube_url:
                QDesktopServices.openUrl(QUrl(self.model.tracks[r].youtube_url))

    def _copiar_seleccion(self):
        urls = [self.model.tracks[r].youtube_url for r in self._filas_seleccionadas() if self.model.tracks[r].youtube_url]
        if urls:
            QGuiApplication.clipboard().setText("\n".join(urls))

    def _quitar_seleccion(self):
        if not self.ocupado:
            self.model.remove_rows(self._filas_seleccionadas())

    def _reintentar_fallidas(self):
        rows = [i for i, t in enumerate(self.model.tracks) if t.status in (Status.FAILED, Status.PENDING)]
        self._buscar_filas(rows, use_cache=False)

    def _copiar_todo(self):
        urls = [t.youtube_url for t in self.model.tracks if t.youtube_url]
        QGuiApplication.clipboard().setText("\n".join(urls))
        self.lbl_fase.setText(f"{len(urls)} enlaces copiados al portapapeles")

    def _exportar(self, ext: str):
        inicial = str(Path(self.ajustes["out_dir"]) / default_name(ext))
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar", inicial, FORMATOS[ext])
        if not ruta:
            return
        try:
            n = export(self.model.tracks, Path(ruta))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Exportar", str(e))
            return
        self.ultimo_archivo = Path(ruta)
        self.ajustes["out_dir"] = str(Path(ruta).parent)
        self.lbl_fase.setText(f"Exportadas {n} filas a {Path(ruta).name}")
        self.btn_archivo.setVisible(True)

    def _mostrar_archivo(self):
        if self.ultimo_archivo:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ultimo_archivo.parent)))

    def _abrir_ajustes(self):
        DialogoAjustes(self.ajustes, self).exec()

    def _texto_tema(self):
        self.btn_tema.setText("☀  Claro" if self.ajustes["theme"] == "dark" else "☾  Oscuro")

    def _cambiar_tema(self):
        self.ajustes["theme"] = "light" if self.ajustes["theme"] == "dark" else "dark"
        aplicar_tema(QApplication.instance(), self.ajustes["theme"])
        self._texto_tema()

    def closeEvent(self, event):
        if self.ocupado:
            self.worker.cancel.set()
            self.worker.wait(8000)
        super().closeEvent(event)


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


if __name__ == "__main__":
    sys.exit(main())
