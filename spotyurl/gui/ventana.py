"""Ventana principal."""

import dataclasses
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QMimeData, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QStackedWidget, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from .. import actualizar, youtube
from ..export import FORMATOS, IMPORTABLES, default_name, export, from_csv, to_txt, unique_path
from ..manifiesto import ARCHIVO_MANIFIESTO, leer_manifiesto
from ..models import Status
from ..paths import safe_filename
from ..spotify import parse_source, parse_text_list
from .ajustes import Ajustes
from .constantes import CACHE_PATH, ICON_PATH, plural
from .dialogo_actualizar import abrir_actualizar, texto_version
from .dialogo_ajustes import DialogoAjustes
from .dialogo_candidatos import DialogoCandidatos, esperar_busquedas
from .dialogo_descarga import DialogoDescarga
from .modelo import FiltroTracks, TrackTableModel
from .tema import aplicar_tema, colores_estado, repolish
from .workers import DownloadWorker, Worker


# ── Ventana principal ────────────────────────────────────────────────────────

FILTROS_ESTADO = [
    ("Todas", None),
    ("Encontradas", {Status.OK, Status.MANUAL}),
    ("Dudosas", {Status.DOUBTFUL}),
    ("Sin enlace", {Status.FAILED}),
    ("Pendientes", {Status.PENDING, Status.SEARCHING}),
]
FILTRO_TODAS, FILTRO_ENCONTRADAS, FILTRO_DUDOSAS, FILTRO_SIN_ENLACE = 0, 1, 2, 3
# Filtro que pone cada chip de estado al pulsarlo
FILTRO_CHIP = {Status.OK: FILTRO_ENCONTRADAS, Status.DOUBTFUL: FILTRO_DUDOSAS, Status.FAILED: FILTRO_SIN_ENLACE}
# Ancho inicial de cada columna (la última, el enlace, ocupa el resto)
ANCHOS_COLUMNAS = (48, 260, 180, 76, 120, 100, 260)


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


def atajo(secuencia) -> str:
    """Texto del atajo para los tooltips (en macOS sale ⌘ en vez de Ctrl)."""
    return QKeySequence(secuencia).toString(QKeySequence.NativeText)


def texto_restante(segundos: float) -> str:
    """Estimación legible del tiempo que falta: 'quedan ~2 min'."""
    if segundos < 45:
        return "queda menos de 1 min"
    minutos = round(segundos / 60)
    if minutos < 60:
        return "queda ~1 min" if minutos == 1 else f"quedan ~{minutos} min"
    h, m = divmod(minutos, 60)
    return f"quedan ~{h} h {m:02d} min"


def nombre_corto(t) -> str:
    """'Artista – Título' para la línea de progreso."""
    return f"{t.artist} – {t.title}" if t.artists else t.title


def ruta_autoguardado(carpeta: Path, nombre_lista: str) -> Path:
    """
    .txt del auto-guardado. Con nombre de lista se sobrescribe el de la conversión
    anterior de esa misma lista (no se acumulan «(2)», «(3)»…); sin nombre, el
    archivo lleva la fecha y unique_path solo evita choques en el mismo segundo.
    """
    if safe_filename(nombre_lista):
        return carpeta / default_name("txt", nombre_lista)
    return unique_path(carpeta / default_name("txt"))


def contenido_drop(mime: QMimeData) -> tuple[str, str] | None:
    """
    ("enlace", url de Spotify), ("archivo", ruta de un .txt) o ("csv", ruta de
    un .csv) de lo arrastrado; None si no sirve.
    """
    for u in mime.urls():
        if u.isLocalFile() and u.toLocalFile().lower().endswith(".txt"):
            return "archivo", u.toLocalFile()
        if u.isLocalFile() and u.toLocalFile().lower().endswith(".csv"):
            return "csv", u.toLocalFile()
        src = parse_source(u.toString()) if "spotify" in u.toString().lower() else None
        if src:
            return "enlace", src.url
    if mime.hasText():
        texto = mime.text().strip()
        src = parse_source(texto) if "spotify" in texto.lower() else None
        if src:
            return "enlace", src.url
    return None


def texto_reciente(r: dict) -> str:
    """«Nombre — 22/10/2026» para el menú Recientes."""
    nombre = r["nombre"] or r["url"]
    if len(nombre) > 50:
        nombre = nombre[:49] + "…"
    try:
        return f"{nombre} — {datetime.fromisoformat(r['fecha']).strftime('%d/%m/%Y')}"
    except ValueError:
        return nombre


class EtiquetaElidida(QLabel):
    """QLabel de una línea que recorta el texto con «…» al ancho disponible (completo en el tooltip)."""

    def __init__(self, texto: str = "", **kwargs):
        super().__init__(**kwargs)
        # Ignored: el ancho lo decide el layout, no la longitud del texto
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(60)
        self._completo = ""
        self.setText(texto)

    def setText(self, texto: str):
        self._completo = texto
        self.setToolTip(texto)
        self._elidir()

    def texto_completo(self) -> str:
        return self._completo

    def _elidir(self):
        ancho = max(self.width(), 60)
        super().setText(QFontMetrics(self.font()).elidedText(self._completo, Qt.ElideRight, ancho))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elidir()


class Chip(QLabel):
    """Contador de un estado; al pulsarlo filtra la tabla por ese estado."""

    clicked = Signal()

    def __init__(self):
        super().__init__(objectName="chip")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, ajustes: Ajustes | None = None):
        super().__init__()
        # `ajustes` permite usar otro almacén (p. ej. un .ini en los tests)
        self.ajustes = ajustes if ajustes is not None else Ajustes()
        self.worker: Worker | None = None
        self.ultima_carpeta: Path | None = None   # la que abre «Abrir carpeta»
        self.nombre_lista = ""   # nombre de la playlist/álbum ("" en «Lista de texto»)
        self.origen_lista = ""   # enlace de Spotify de la lista de la tabla ("" en texto/.csv)
        self._cerrar_al_terminar = False          # se pidió salir con trabajo en curso
        self._ultimo_autopegado = ""
        # Línea de progreso: fase, total, hechas y canción en curso
        self._fase, self._total, self._hechas = "", 0, 0
        self._en_curso = ""             # «Artista – Título» de la canción en curso
        self._verbo = ""                # «Buscando» / «Descargando»
        self._audio_actual = None       # fila que se está descargando
        self._t_inicio = 0.0            # cuándo empezó a descargarse
        self._duraciones: list[float] = []   # segundos de cada canción descargada (estimación)
        self.setWindowTitle("Spotify to You-rl")
        self.resize(1120, 760)
        self.setMinimumSize(820, 560)
        self.setAcceptDrops(True)

        self.model = TrackTableModel(self.ajustes["theme"])
        self.model.enlace_rechazado.connect(self._on_enlace_rechazado)
        self.model.enlace_editado.connect(self._recordar)
        self.proxy = FiltroTracks()
        self.proxy.setSourceModel(self.model)

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        lay.addLayout(self._cabecera())
        lay.addWidget(self._entrada())
        lay.addWidget(self._aviso_ytdlp())
        lay.addLayout(self._estado())
        lay.addLayout(self._filtros())
        lay.addWidget(self._tabla(), 1)
        lay.addLayout(self._pie())
        self.log_view = QPlainTextEdit(readOnly=True, maximumBlockCount=2000)
        self.log_view.setFixedHeight(140)
        self.log_view.setVisible(False)
        lay.addWidget(self.log_view)
        self._atajos()

        for sig in (self.model.dataChanged, self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset):
            sig.connect(self._refrescar)
        self._restaurar_estado_ui()
        self._validar_entrada()
        self._refrescar()
        self._comprobar_ytdlp()
        # Autopegado al volver a la app con un enlace de Spotify en el portapapeles
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_estado_app)

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
        # Cmd+, en macOS (en Windows no hay atajo estándar y no hace nada)
        preferencias = QAction(self, shortcut=QKeySequence(QKeySequence.Preferences))
        preferencias.triggered.connect(self._abrir_ajustes)
        self.addAction(preferencias)

        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON_PATH)).pixmap(44, 44))

        self.btn_recientes = QToolButton(text="Recientes  ▾", objectName="ghost", popupMode=QToolButton.InstantPopup)
        self.btn_recientes.setToolTip("Volver a convertir o actualizar una lista reciente")
        self.menu_recientes = QMenu(self.btn_recientes)
        self.menu_recientes.aboutToShow.connect(self._construir_menu_recientes)
        self.btn_recientes.setMenu(self.menu_recientes)

        h = QHBoxLayout()
        h.setSpacing(12)
        h.addWidget(logo)
        h.addLayout(col, 1)
        h.addWidget(self.btn_recientes)
        h.addWidget(self.btn_tema)
        h.addWidget(btn_ajustes)
        return h

    def _entrada(self):
        c = self.tarjeta_entrada = card()
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
        self.url.setToolTip(f"Enlace de Spotify ({atajo('Ctrl+L')})")
        self.url.setAcceptDrops(False)   # lo arrastrado lo gestiona la ventana (rellena y convierte)
        self.url.textChanged.connect(self._validar_entrada)
        self.url.returnPressed.connect(self._convertir)
        pegar = QPushButton("Pegar")
        pegar.setToolTip("Pega el enlace del portapapeles y, si es válido, convierte")
        pegar.clicked.connect(self._pegar)
        pagina_url = QWidget()
        hu = QHBoxLayout(pagina_url)
        hu.setContentsMargins(0, 0, 0, 0)
        hu.addWidget(self.url, 1)
        hu.addWidget(pegar)

        self.texto = QPlainTextEdit(placeholderText="Una canción por línea:\nBruno Mars - Locked Out of Heaven\nRosalía - Despechá")
        self.texto.setFixedHeight(110)
        self.texto.setAcceptDrops(False)
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

    def _aviso_ytdlp(self):
        """Franja discreta (oculta salvo que yt-dlp sea antiguo) con «Actualizar» y «×»."""
        f = self.aviso_ytdlp = QFrame(objectName="aviso")
        self.lbl_aviso_ytdlp = QLabel()
        self.lbl_aviso_ytdlp.setWordWrap(True)
        btn = QPushButton("Actualizar")
        btn.clicked.connect(self._actualizar_ytdlp)
        cerrar = self.btn_cerrar_aviso = QPushButton("×", objectName="ghost")
        cerrar.setToolTip("Ocultar el aviso")
        cerrar.clicked.connect(lambda: f.setVisible(False))
        h = QHBoxLayout(f)
        h.setContentsMargins(12, 6, 6, 6)
        h.addWidget(self.lbl_aviso_ytdlp, 1)
        h.addWidget(btn)
        h.addWidget(cerrar)
        f.setVisible(False)
        return f

    def _estado(self):
        self.lbl_fase = EtiquetaElidida("Listo", objectName="muted")
        self.btn_archivo = QPushButton("Abrir carpeta", objectName="ghost")
        self.btn_archivo.setVisible(False)
        self.btn_archivo.clicked.connect(self._abrir_carpeta)
        self.barra = QProgressBar(textVisible=False)
        self.barra.setVisible(False)
        self.btn_cancelar = QPushButton("Cancelar", objectName="cancelar")
        self.btn_cancelar.setToolTip("Cancelar (Esc)")
        self.btn_cancelar.setVisible(False)
        self.btn_cancelar.clicked.connect(self._cancelar)
        self.chips = {Status.OK: Chip(), Status.DOUBTFUL: Chip(), Status.FAILED: Chip()}
        h = QHBoxLayout()
        h.addWidget(self.lbl_fase, 1)
        h.addWidget(self.btn_archivo)
        h.addWidget(self.barra, 1)
        h.addWidget(self.btn_cancelar)
        for estado, chip in self.chips.items():
            chip.clicked.connect(lambda e=estado: self._on_chip(e))
            h.addWidget(chip)
        return h

    def _filtros(self):
        self.filtro_texto = QLineEdit(placeholderText="Filtrar por título, artista o álbum…")
        self.filtro_texto.setClearButtonEnabled(True)
        self.filtro_texto.setToolTip(f"Filtrar ({atajo('Ctrl+F')})")
        self.filtro_estado = QComboBox()
        for nombre, _ in FILTROS_ESTADO:
            self.filtro_estado.addItem(nombre)
        self.filtro_texto.textChanged.connect(self._aplicar_filtro)
        self.filtro_estado.currentIndexChanged.connect(self._aplicar_filtro)
        self.btn_revisar = QPushButton("Revisar dudosas")
        self.btn_revisar.setToolTip("Recorre las dudosas una a una para elegir la versión correcta")
        self.btn_revisar.clicked.connect(self._revisar_dudosas)
        h = QHBoxLayout()
        h.addWidget(self.filtro_texto, 1)
        h.addWidget(self.filtro_estado)
        h.addWidget(self.btn_revisar)
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
        for col, ancho in enumerate(ANCHOS_COLUMNAS):
            self.tabla.setColumnWidth(col, ancho)
        hh.setStretchLastSection(True)
        # Ordenar por columnas (# y Duración como números, ver FiltroTracks); por defecto, el orden de la lista
        hh.setSortIndicator(TrackTableModel.COL_NUM, Qt.AscendingOrder)
        self.tabla.setSortingEnabled(True)
        self.tabla.setColumnHidden(TrackTableModel.COL_AUDIO, True)   # se muestra al descargar
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)
        self.tabla.doubleClicked.connect(self._doble_clic)

        copiar = QAction(self.tabla, shortcut=QKeySequence(QKeySequence.Copy), shortcutContext=Qt.WidgetShortcut)
        copiar.triggered.connect(self._copiar_seleccion)
        borrar = QAction(self.tabla, shortcutContext=Qt.WidgetShortcut)
        # En el teclado de Mac la tecla "delete" es Backspace
        borrar.setShortcuts([QKeySequence(QKeySequence.Delete), QKeySequence(Qt.Key_Backspace)])
        borrar.triggered.connect(self._quitar_seleccion)
        self.tabla.addActions([copiar, borrar])
        # Ctrl+E: elegir otra versión de la canción seleccionada (Cmd+E en macOS)
        self.accion_elegir = QAction("Elegir otra versión…", self, shortcut=QKeySequence("Ctrl+E"))
        self.accion_elegir.triggered.connect(self._elegir_version)
        self.addAction(self.accion_elegir)

        self.vacio = QLabel(
            "Pega el enlace de una playlist o álbum público de Spotify y pulsa <b>Convertir</b>,<br>"
            "o arrastra aquí un enlace, un .txt con una canción por línea o un .csv (Exportify o de esta app).<br>"
            "También puedes pegar una lista de canciones en «Lista de texto».",
            objectName="empty", alignment=Qt.AlignCenter,
        )
        self.stack_tabla = QStackedWidget()
        self.stack_tabla.addWidget(self.vacio)
        self.stack_tabla.addWidget(self.tabla)
        return self.stack_tabla

    def _pie(self):
        self.btn_reintentar = QPushButton("↻  Reintentar fallidas")
        self.btn_reintentar.clicked.connect(self._reintentar_fallidas)
        self.btn_copiar = QPushButton("Copiar todo")
        self.btn_copiar.setToolTip(f"Copiar todos los enlaces ({atajo('Ctrl+Shift+C')})")
        self.btn_copiar.clicked.connect(self._copiar_todo)
        # «Archivo»: abrir un .csv, exportar y actualizar una descarga
        self.btn_exportar = QToolButton(text="Archivo  ▾", popupMode=QToolButton.InstantPopup)
        self.btn_exportar.setToolTip("Abrir un .csv, exportar la lista o actualizar una descarga")
        menu = QMenu(self.btn_exportar)
        menu.addAction("Abrir .csv…", lambda: self._abrir_csv()).setToolTip(
            "Carga un .csv exportado por esta app o por Exportify")
        menu.addSeparator()
        self.acciones_exportar = [menu.addAction(f"Exportar · {desc}", lambda e=ext: self._exportar(e))
                                  for ext, desc in FORMATOS.items()]
        menu.addSeparator()
        menu.addAction("⟳  Actualizar descarga…", lambda: self._actualizar_descarga()).setToolTip(
            "Trae lo nuevo de la playlist de una carpeta ya descargada")
        menu.setToolTipsVisible(True)
        self.btn_exportar.setMenu(menu)
        self.btn_descargar = QPushButton("⬇  Descargar audio")
        self.btn_descargar.setToolTip("Descarga el audio de las canciones con enlace a una carpeta")
        self.btn_descargar.clicked.connect(lambda: self._descargar())
        self.btn_log = QPushButton("Log", objectName="ghost", checkable=True)
        self.btn_log.toggled.connect(self._on_log)

        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(self.btn_log)
        h.addWidget(self.btn_reintentar)
        h.addWidget(self.btn_copiar)
        h.addWidget(self.btn_exportar)
        h.addWidget(self.btn_descargar)
        return h

    def _atajos(self):
        def accion(teclas, slot, contexto=Qt.WindowShortcut) -> QAction:
            a = QAction(self, shortcutContext=contexto)
            a.setShortcuts([QKeySequence(t) for t in teclas])
            a.triggered.connect(slot)
            self.addAction(a)
            return a

        # Return del teclado principal y Enter del numérico; funciona también en «Lista de texto»
        accion(["Ctrl+Return", "Ctrl+Enter"], self._atajo_convertir)
        # Solo activa con trabajo en curso: así no roba Esc a editores ni menús
        self.accion_cancelar = accion(["Esc"], self._cancelar)
        self.accion_cancelar.setEnabled(False)
        accion(["Ctrl+F"], self._foco_filtro)
        accion(["Ctrl+L"], self._foco_enlace)
        accion(["Ctrl+Shift+C"], lambda: self.btn_copiar.isEnabled() and self._copiar_todo())
        self.btn_convertir.setToolTip(f"Convertir ({atajo('Ctrl+Return')})")
        self.accion_elegir.setToolTip(f"Elegir otra versión ({atajo('Ctrl+E')})")

    # Estado de la UI ─────────────────────────────────────────────────────────

    @property
    def ocupado(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _cambiar_modo(self, idx: int):
        self.modo = idx
        (self.seg_enlace, self.seg_texto)[idx].setChecked(True)
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
            self.lbl_ayuda.setText(plural(n, "canción", "canciones") if n else "")
            ok = n > 0
        if not self.ocupado:
            self.btn_convertir.setEnabled(ok)

    def _refrescar(self):
        c = self.model.counts()
        color = colores_estado(self.ajustes["theme"])
        textos = {
            Status.OK: plural(c[Status.OK] + c[Status.MANUAL], "encontrada", "encontradas"),
            Status.DOUBTFUL: plural(c[Status.DOUBTFUL], "dudosa", "dudosas"),
            Status.FAILED: f"{c[Status.FAILED]} sin enlace",
        }
        hay = bool(self.model.tracks)
        filtro = self.filtro_estado.currentIndex()
        for estado, chip in self.chips.items():
            chip.setText(f"<span style='color:{color[estado]}'>●</span>  {textos[estado]}")
            chip.setVisible(hay)
            activo = filtro == FILTRO_CHIP[estado]
            if chip.property("activo") != activo:
                chip.setProperty("activo", activo)
                repolish(chip)
            chip.setToolTip("Mostrar todas" if activo else f"Mostrar solo: {FILTROS_ESTADO[FILTRO_CHIP[estado]][0].lower()}")
        self.stack_tabla.setCurrentIndex(1 if hay else 0)
        # La columna Audio solo aparece cuando hay una descarga (en curso o terminada)
        sin_audio = not self.model.audio
        if self.tabla.isColumnHidden(TrackTableModel.COL_AUDIO) != sin_audio:
            self.tabla.setColumnHidden(TrackTableModel.COL_AUDIO, sin_audio)
        con_enlace = any(t.youtube_url for t in self.model.tracks)
        libre = not self.ocupado
        self.btn_copiar.setEnabled(con_enlace and libre)
        self.btn_exportar.setEnabled(libre)
        for a in self.acciones_exportar:
            a.setEnabled(hay)
        self.btn_recientes.setEnabled(libre)
        self.btn_descargar.setEnabled(con_enlace and libre)
        self.btn_reintentar.setEnabled(libre and c[Status.FAILED] + c[Status.PENDING] > 0
                                       and c[Status.PENDING] != len(self.model.tracks))
        self.btn_revisar.setVisible(c[Status.DOUBTFUL] > 0)
        self.btn_revisar.setEnabled(libre)
        self.accion_elegir.setEnabled(libre and hay)

    def _set_ocupado(self, ocupado: bool):
        # Mientras hay trabajo, Convertir se desactiva y se cancela con el botón junto a la barra (o Esc)
        self.btn_convertir.setEnabled(not ocupado)
        for w in (self.seg_enlace, self.seg_texto, self.url, self.texto):
            w.setEnabled(not ocupado)
        self.barra.setVisible(ocupado)
        self.btn_cancelar.setVisible(ocupado)
        self.btn_cancelar.setEnabled(ocupado)
        self.accion_cancelar.setEnabled(ocupado)
        # El hilo reemplaza las filas: una edición a mano se perdería (setData la rechaza)
        self.model.editable = not ocupado
        if not ocupado:
            self._validar_entrada()
        self._refrescar()

    def _aplicar_filtro(self):
        self.proxy.set_filtro(self.filtro_texto.text(), FILTROS_ESTADO[self.filtro_estado.currentIndex()][1])
        self._refrescar()   # resalta el chip del filtro activo

    def _on_chip(self, estado: Status):
        """Pulsar un chip filtra por su estado; pulsarlo otra vez vuelve a «Todas»."""
        filtro = FILTRO_CHIP[estado]
        self.filtro_estado.setCurrentIndex(FILTRO_TODAS if self.filtro_estado.currentIndex() == filtro else filtro)

    def _log(self, msg: str):
        self.log_view.appendPlainText(msg.rstrip())

    def _set_errores_log(self, n: int):
        self.btn_log.setText(f"Log ({n})" if n else "Log")
        self.btn_log.setToolTip(f"{plural(n, 'error', 'errores')} en la última operación" if n else "")

    def _on_log(self, visible: bool):
        self.log_view.setVisible(visible)
        self.ajustes["log_open"] = visible

    # Estado persistente de la ventana ────────────────────────────────────────

    def _restaurar_estado_ui(self):
        geometria = self.ajustes.get_bytes("ui/geometry")
        if geometria is not None:
            self.restoreGeometry(geometria)
        cabecera = self.ajustes.get_bytes("ui/header")
        # Una cabecera guardada con otras columnas (versión anterior) descolocaría los anchos
        if cabecera is not None and self.ajustes["header_cols"] == self.model.columnCount():
            self.tabla.horizontalHeader().restoreState(cabecera)
        self._cambiar_modo(1 if self.ajustes["input_mode"] == 1 else 0)
        self.btn_log.setChecked(self.ajustes["log_open"])

    def _guardar_estado_ui(self):
        self.ajustes.set_bytes("ui/geometry", self.saveGeometry())
        self.ajustes.set_bytes("ui/header", self.tabla.horizontalHeader().saveState())
        self.ajustes["header_cols"] = self.model.columnCount()
        self.ajustes["input_mode"] = self.modo
        self.ajustes["log_open"] = self.btn_log.isChecked()

    # Arrastrar y soltar / portapapeles ───────────────────────────────────────

    def _resaltar_entrada(self, si: bool):
        self.tarjeta_entrada.setProperty("drop", si)
        repolish(self.tarjeta_entrada)

    def dragEnterEvent(self, event):
        if not self.ocupado and contenido_drop(event.mimeData()):
            event.acceptProposedAction()
            self._resaltar_entrada(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._resaltar_entrada(False)

    def dropEvent(self, event):
        self._resaltar_entrada(False)
        contenido = None if self.ocupado else contenido_drop(event.mimeData())
        if not contenido:
            event.ignore()
            return
        event.acceptProposedAction()
        tipo, valor = contenido
        if tipo == "enlace":
            self._cambiar_modo(0)
            self.url.setText(valor)
            self._convertir()
            return
        if tipo == "csv":
            self._abrir_csv(Path(valor))
            return
        try:
            texto = Path(valor).read_text(encoding="utf-8-sig", errors="ignore")
        except OSError as e:
            self.lbl_fase.setText(f"No se pudo leer {Path(valor).name}: {e}")
            return
        self._cambiar_modo(1)
        self.texto.setPlainText(texto)
        self.lbl_fase.setText(f"Lista cargada de {Path(valor).name}: pulsa Convertir")

    def _pegar(self):
        self._cambiar_modo(0)
        self.url.setText(QGuiApplication.clipboard().text().strip())
        if self.btn_convertir.isEnabled() and not self.ocupado:
            self._convertir()

    def _on_estado_app(self, estado):
        if estado == Qt.ApplicationActive:
            self._autopegar()

    def _autopegar(self):
        if self.ocupado or self.modo != 0 or self.url.text().strip():
            return
        texto = QGuiApplication.clipboard().text().strip()
        if "spotify" not in texto.lower() or len(texto) > 2000:
            return
        src = parse_source(texto)
        if not src or src.url == self._ultimo_autopegado:
            return
        self._ultimo_autopegado = src.url
        self.url.setText(src.url)
        self.lbl_ayuda.setText("Enlace pegado desde el portapapeles")

    # Atajos ──────────────────────────────────────────────────────────────────

    def _atajo_convertir(self):
        if not self.ocupado:
            self._convertir()

    def _cancelar(self):
        if self.ocupado:
            self.worker.cancel.set()
            self.btn_cancelar.setEnabled(False)
            self.lbl_fase.setText("Cancelando…")

    def _foco_filtro(self):
        self.filtro_texto.setFocus(Qt.ShortcutFocusReason)
        self.filtro_texto.selectAll()

    def _foco_enlace(self):
        if self.ocupado:
            return
        self._cambiar_modo(0)
        self.url.setFocus(Qt.ShortcutFocusReason)
        self.url.selectAll()

    # Acciones ────────────────────────────────────────────────────────────────

    def _convertir(self):
        if self.ocupado or not self.btn_convertir.isEnabled():
            return
        if self.modo == 0:
            # Forma canónica del enlace (sin ?si=…): es la que se recuerda en Recientes y en la carpeta
            url = parse_source(self.url.text().strip()).url
            self._nueva_lista(origen=url)
            self._lanzar(Worker(self.ajustes.snapshot(), url=url))
        else:
            tracks = parse_text_list(self.texto.toPlainText())
            self._nueva_lista(tracks)
            self._lanzar(Worker(self.ajustes.snapshot(), items=[(i, dataclasses.replace(t)) for i, t in enumerate(tracks)]))

    def _nueva_lista(self, tracks: list | None = None, nombre: str = "", origen: str = ""):
        """Cambia de lista: pone `tracks` en la tabla (vacía si no hay) y su nombre y enlace."""
        self.btn_archivo.setVisible(False)
        self.nombre_lista, self.origen_lista = nombre, origen
        self.filtro_estado.setCurrentIndex(0)   # un filtro de la lista anterior escondería filas
        self.model.set_tracks(tracks or [])

    def _buscar_filas(self, rows: list[int], use_cache: bool, guardar: bool = False):
        if self.ocupado or not rows:
            return
        items = [(r, dataclasses.replace(self.model.tracks[r])) for r in sorted(rows)]
        self._lanzar(Worker(self.ajustes.snapshot(), items=items, use_cache=use_cache), guardar=guardar)

    def _lanzar(self, w: Worker, guardar: bool = True):
        self.worker = w
        self._set_errores_log(0)
        w.tracks_reset.connect(self.model.set_tracks)
        w.track_added.connect(self.model.add_track)
        w.track_updated.connect(self._on_track_actualizado)
        if isinstance(w, DownloadWorker):
            w.audio_estado.connect(self._on_audio)
        w.phase.connect(self._on_fase)
        w.progress.connect(self._on_progreso)
        w.log.connect(self._log)
        w.copy_request.connect(lambda url: QGuiApplication.clipboard().setText(url))
        w.failed.connect(self._on_error)
        w.name_found.connect(self._on_nombre)
        w.finished.connect(lambda: self._on_fin(w, guardar))
        w.start()
        self._set_ocupado(True)

    def _on_fase(self, texto: str, total: int):
        self._fase, self._total, self._hechas = texto, total, 0
        self._en_curso, self._verbo = "", ""
        self._audio_actual, self._duraciones = None, []
        self.barra.setRange(0, total)
        self.barra.setValue(0)
        self._texto_progreso()
        self._log(f"── {texto}")

    def _on_progreso(self, k: int):
        self._hechas = k
        self.barra.setValue(k)
        self._texto_progreso()

    def _texto_progreso(self):
        """«Descargando 3/40 · Artista – Título · quedan ~2 min» (o «Buscando 12/40 · …»)."""
        if self.worker is not None and self.worker.cancel.is_set():
            return   # «Cancelando…» se queda hasta que el hilo termine
        if not self._total:
            self.lbl_fase.setText(self._fase)
            return
        if not self._en_curso:
            self.lbl_fase.setText(f"{self._fase} {self._hechas}/{self._total}")
            return
        n = min(self._hechas + 1, self._total)
        texto = f"{self._verbo} {n}/{self._total} · {self._en_curso}"
        if self._verbo == "Descargando" and self._duraciones:
            # Media de las canciones ya descargadas × las que faltan, menos lo que lleva la actual
            media = sum(self._duraciones) / len(self._duraciones)
            restante = media * (self._total - self._hechas)
            if self._audio_actual is not None:
                restante -= min(media, time.monotonic() - self._t_inicio)
            texto += f" · {texto_restante(max(0.0, restante))}"
        self.lbl_fase.setText(texto)

    def _on_track_actualizado(self, row: int, t):
        self.model.update_track(row, t)
        if t.status == Status.SEARCHING:
            self._verbo, self._en_curso = "Buscando", nombre_corto(t)
            self._texto_progreso()

    def _on_audio(self, row: int, estado: str, pct: float):
        from ..download import ESTADO_DESCARGANDO, ESTADO_ERROR, ESTADO_OK

        self.model.set_audio(row, estado, pct)
        ahora = time.monotonic()
        if estado == ESTADO_DESCARGANDO and row != self._audio_actual:
            self._audio_actual, self._t_inicio = row, ahora
            if 0 <= row < len(self.model.tracks):
                self._verbo, self._en_curso = "Descargando", nombre_corto(self.model.tracks[row])
        elif estado in (ESTADO_OK, ESTADO_ERROR) and row == self._audio_actual:
            self._duraciones.append(ahora - self._t_inicio)
            self._audio_actual = None
        self._texto_progreso()

    def _on_nombre(self, nombre: str):
        self.nombre_lista = nombre.strip()
        if self.nombre_lista:
            self._log(f"Lista: {self.nombre_lista}")

    def _on_error(self, msg: str):
        self._log(msg)
        if not self._cerrar_al_terminar:
            QMessageBox.warning(self, "No se pudo completar", msg)

    def _on_enlace_rechazado(self, texto: str):
        corto = texto if len(texto) <= 60 else texto[:57] + "…"
        self.lbl_fase.setText(f"«{corto}» no es un enlace de YouTube: no se ha cambiado")

    def _on_fin(self, w: Worker, guardar: bool):
        cancelado = w.cancel.is_set()
        self.worker = None
        w.deleteLater()
        self._set_ocupado(False)
        self._set_errores_log(w.errores)
        if self._cerrar_al_terminar:
            # Se pidió salir con el trabajo en curso: el hilo ya terminó, ahora sí
            QTimer.singleShot(0, self.close)
            return
        if not self.isActiveWindow():
            QApplication.alert(self)   # parpadea en la barra de tareas / rebota en el Dock
        if isinstance(w, DownloadWorker):
            # Ni mensaje de conversión ni auto-guardado del .txt tras una descarga
            self._fin_descarga(w, cancelado)
            return
        tracks = self.model.tracks
        n_links = sum(bool(t.youtube_url) for t in tracks)
        estado = "Cancelado" if cancelado else "Listo"
        titulo = f"«{self.nombre_lista}» · " if self.nombre_lista else ""
        self.lbl_fase.setText(f"{estado}: {titulo}{n_links} de {plural(len(tracks), 'canción', 'canciones')} con enlace")
        if w.url and tracks and not w.fallo:
            self.ajustes.agregar_reciente(w.url, self.nombre_lista, w.sync_folder or "")
        if guardar and n_links and w.opts["auto_save"] and not cancelado:
            carpeta = Path(self.ajustes["out_dir"])
            try:
                carpeta.mkdir(parents=True, exist_ok=True)
                archivo = ruta_autoguardado(carpeta, self.nombre_lista)
                to_txt(tracks, archivo)
                self._log(f"Guardado: {archivo}")
                self.lbl_fase.setText(self.lbl_fase.texto_completo() + f"  ·  {archivo.name}")
                self.ultima_carpeta = carpeta
                self.btn_archivo.setVisible(True)
            except OSError as e:
                self._log(f"No se pudo guardar el .txt: {e}")
        if w.sync_folder is not None and not cancelado and not w.fallo and tracks:
            self._descargar_sincronizacion(w)

    def _fin_descarga(self, w: DownloadWorker, cancelado: bool):
        r = w.result
        if r is None:   # el error ya se avisó con la señal failed
            self.lbl_fase.setText("La descarga no se pudo completar")
            self.btn_log.setChecked(True)
            return
        fila = {id(t): i for i, t in enumerate(w.tracks)}
        for t, motivo in r.failed:
            self._log(f"No se pudo descargar «{t.label}»: {motivo}")
            if id(t) in fila:
                self.model.set_motivo_audio(fila[id(t)], motivo)   # tooltip de la columna Audio
        resumen = (f"Descargadas {len(r.ok)} · ya estaban {len(r.skipped)} · renumeradas {len(r.renamed)}"
                   f" · quitadas {len(r.removed)} · fallidas {len(r.failed)}")
        if w.dudosas:
            resumen += f" · {plural(w.dudosas, 'dudosa', 'dudosas')} para revisar"
        self.lbl_fase.setText(f"Cancelado: {resumen}" if cancelado else resumen)
        self._log(resumen)
        if r.removed and not w.mover_quitadas:
            self._log("Las quitadas siguen en la carpeta; para moverlas a «Quitadas», "
                      "actualiza la descarga marcando esa opción.")
        if w.folder.is_dir():
            self.ultima_carpeta = w.folder
            self.btn_archivo.setVisible(True)
            self.btn_archivo.setToolTip(f"Abrir {w.folder} (incluye la lista {w.album or w.folder.name}.m3u8)")
            if w.origen:
                self.ajustes.agregar_reciente(w.origen, w.album or w.folder.name, w.folder)
        if r.failed and not r.ok and not cancelado:
            # Si no se descargó nada, avisar en grande y abrir el log: ahí está el detalle
            from ..download import pista_error

            self.btn_log.setChecked(True)
            t, motivo = r.failed[0]
            pista = pista_error(motivo)
            ofrecer = "yt-dlp" in pista   # 403 / nsig / «not a bot»: se arregla actualizando yt-dlp
            caja = self._caja_fallo_descarga(
                f"No se pudo descargar ninguna canción ({len(r.failed)} fallidas).\n\n"
                f"Primer error («{t.label}»):\n{motivo}" + (f"\n\n{pista}" if pista else ""),
                ofrecer,
            )
            caja.exec()
            if ofrecer and caja.clickedButton() is self.btn_actualizar_aviso:
                self._actualizar_ytdlp()

    def _caja_fallo_descarga(self, texto: str, ofrecer_actualizar: bool) -> QMessageBox:
        caja = QMessageBox(QMessageBox.Warning, "Descargar audio", texto, QMessageBox.Ok, self)
        self.btn_actualizar_aviso = None
        if ofrecer_actualizar:
            self.btn_actualizar_aviso = caja.addButton("Actualizar yt-dlp ahora", QMessageBox.AcceptRole)
        return caja

    # yt-dlp ──────────────────────────────────────────────────────────────────

    def _comprobar_ytdlp(self, hoy=None):
        """Al arrancar: si yt-dlp tiene más de DIAS_AVISO días, mostrar la franja (nunca un diálogo)."""
        v = actualizar.version_ytdlp()
        dias = actualizar.dias_desde_version(v, hoy)
        if dias is not None and dias > actualizar.DIAS_AVISO:
            self.lbl_aviso_ytdlp.setText(f"{texto_version(v, hoy)}. Si las descargas fallan "
                                         "(403, «not a bot»), actualízalo.")
            self.aviso_ytdlp.setVisible(True)

    def _actualizar_ytdlp(self):
        if self.ocupado:
            self.lbl_fase.setText("Espera a que termine la conversión/descarga para actualizar yt-dlp")
            return
        d = abrir_actualizar(self)
        if d is not None and d.ok:
            self.aviso_ytdlp.setVisible(False)

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
        menu.addAction("Buscar a mano en YouTube…", lambda: self._buscar_a_mano(t))
        menu.addSeparator()
        libre = not self.ocupado
        if len(rows) == 1:
            menu.addAction(self.accion_elegir)   # Ctrl+E
            self.accion_elegir.setEnabled(libre)
        menu.addAction("Marcar como correcta", lambda: self._marcar_correctas(rows)).setEnabled(
            libre and any(self._se_puede_marcar(r) for r in rows))
        menu.addAction("Reintentar búsqueda", lambda: self._buscar_filas(rows, use_cache=False)).setEnabled(libre)
        menu.addAction("Pegar otro enlace…", lambda: self.tabla.edit(
            self.proxy.mapFromSource(self.model.index(rows[0], TrackTableModel.COL_ENLACE)))).setEnabled(libre)
        menu.addSeparator()
        menu.addAction("⬇  Descargar seleccionadas…", lambda: self._descargar(rows)).setEnabled(
            libre and any(self.model.tracks[r].youtube_url for r in rows))
        menu.addAction("Quitar de la lista", self._quitar_seleccion).setEnabled(libre)
        menu.exec(self.tabla.viewport().mapToGlobal(pos))

    # Correcciones manuales ───────────────────────────────────────────────────

    def _recordar(self, row: int):
        """Guarda en la caché la elección manual de la fila (o la olvida si no tiene enlace)."""
        if self.ajustes["use_cache"] and 0 <= row < len(self.model.tracks):
            youtube.recordar_eleccion(CACHE_PATH, self.model.tracks[row])

    def _fila_actual(self) -> int | None:
        """Fila (del modelo) seleccionada si hay exactamente una."""
        rows = self._filas_seleccionadas()
        return rows[0] if len(rows) == 1 else None

    def _seleccionar_fila_proxy(self, fila_proxy: int) -> bool:
        """Selecciona la fila visible `fila_proxy` (acotada al final). False si no hay filas."""
        n = self.proxy.rowCount()
        if not n:
            return False
        idx = self.proxy.index(min(fila_proxy, n - 1), 0)
        self.tabla.selectionModel().setCurrentIndex(
            idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.tabla.scrollTo(idx)
        return True

    def _fila_proxy(self, row: int) -> int:
        return self.proxy.mapFromSource(self.model.index(row, 0)).row()

    def _tras_corregir(self, fila_proxy: int):
        """Con el filtro «Dudosas», la corregida desaparece: se selecciona la siguiente."""
        if self.filtro_estado.currentIndex() == FILTRO_DUDOSAS and fila_proxy >= 0:
            if self._seleccionar_fila_proxy(fila_proxy):
                self.lbl_fase.setText(f"Siguiente dudosa seleccionada: {atajo('Ctrl+E')} para elegir su versión")

    def _se_puede_marcar(self, row: int) -> bool:
        t = self.model.tracks[row]
        return bool(t.youtube_url) and t.status in (Status.DOUBTFUL, Status.FAILED)

    def _marcar_correctas(self, rows: list[int]):
        if self.ocupado:
            return
        primera = min((self._fila_proxy(r) for r in rows), default=-1)
        marcadas = [r for r in rows if self.model.marcar_correcta(r)]
        for r in marcadas:
            self._recordar(r)
        if marcadas:
            n = len(marcadas)
            self.lbl_fase.setText("Marcada como correcta" if n == 1 else f"{n} canciones marcadas como correctas")
            self._tras_corregir(primera)

    def _elegir_version(self, revision: bool = False) -> int:
        """Abre «Elegir otra versión» para la fila seleccionada. Devuelve el resultado del diálogo."""
        row = self._fila_actual()
        if self.ocupado:
            return 0
        if row is None:
            self.lbl_fase.setText("Selecciona una canción para elegir otra versión")
            return 0
        t = self.model.tracks[row]
        dlg = DialogoCandidatos(dataclasses.replace(t), self.ajustes.snapshot(), self.ajustes["theme"],
                                revision=revision, parent=self)
        r = dlg.exec()
        if self.ocupado or row >= len(self.model.tracks) or self.model.tracks[row] is not t:
            return 0   # la fila cambió mientras el diálogo estaba abierto
        if r == QDialog.Accepted and dlg.elegido is not None:
            self._usar_candidato(row, dlg.elegido, dlg.candidatos)
        elif dlg.candidatos and not t.candidates:
            t.candidates = list(dlg.candidatos)   # la próxima vez no hay que buscarlos
        return r

    def _usar_candidato(self, row: int, cand, candidatos: list | None = None):
        fila_proxy = self._fila_proxy(row)
        self.model.usar_candidato(row, cand, candidatos)
        self._recordar(row)
        self.lbl_fase.setText(f"Versión elegida para «{self.model.tracks[row].label}»: {cand.title}")
        self._tras_corregir(fila_proxy)

    def _revisar_dudosas(self):
        """Recorre las dudosas con el diálogo de candidatos hasta terminar o cerrar."""
        if self.ocupado:
            return
        self.filtro_texto.clear()
        self.filtro_estado.setCurrentIndex(FILTRO_DUDOSAS)
        pos = 0
        while pos < self.proxy.rowCount() and self._seleccionar_fila_proxy(pos):
            r = self._elegir_version(revision=True)
            if r == DialogoCandidatos.SALTAR:
                pos += 1          # sigue dudosa: la siguiente está una fila más abajo
            elif r != QDialog.Accepted:
                return            # «Terminar revisión»
        self.lbl_fase.setText("No quedan canciones dudosas" if not self.proxy.rowCount()
                              else "Revisión terminada: las saltadas siguen como dudosas")

    def _doble_clic(self, index):
        if index.column() == TrackTableModel.COL_ENLACE and self.model.editable:
            return   # la celda de enlace se edita
        t = self.model.tracks[self.proxy.mapToSource(index).row()]
        if t.youtube_url:
            QDesktopServices.openUrl(QUrl(t.youtube_url))
        elif t.status not in (Status.PENDING, Status.SEARCHING):
            self._buscar_a_mano(t)

    def _buscar_a_mano(self, t):
        consulta = QUrl.toPercentEncoding(t.label).data().decode()
        QDesktopServices.openUrl(QUrl(f"https://www.youtube.com/results?search_query={consulta}"))

    def _abrir(self, rows):
        for r in rows[:10]:
            if self.model.tracks[r].youtube_url:
                QDesktopServices.openUrl(QUrl(self.model.tracks[r].youtube_url))

    def _copiar_seleccion(self):
        urls = [self.model.tracks[r].youtube_url for r in self._filas_seleccionadas() if self.model.tracks[r].youtube_url]
        if urls:
            QGuiApplication.clipboard().setText("\n".join(urls))

    def _quitar_seleccion(self):
        if self.ocupado:
            self.lbl_fase.setText("No se pueden quitar canciones mientras hay trabajo en curso")
            return
        self.model.remove_rows(self._filas_seleccionadas())

    def _reintentar_fallidas(self):
        rows = [i for i, t in enumerate(self.model.tracks) if t.status in (Status.FAILED, Status.PENDING)]
        self._buscar_filas(rows, use_cache=False)

    def _copiar_todo(self):
        urls = [t.youtube_url for t in self.model.tracks if t.youtube_url]
        QGuiApplication.clipboard().setText("\n".join(urls))
        self.lbl_fase.setText(f"{plural(len(urls), 'enlace copiado', 'enlaces copiados')} al portapapeles")

    def _descargar(self, filas: list[int] | None = None):
        """Descarga todas las canciones con enlace o, con `filas`, solo esas."""
        from ..download import ffmpeg_disponible

        # Copias de toda la lista (la numeración 01, 02… sigue la posición en la
        # playlist y la fila del modelo = índice en la lista del hilo); el hilo de
        # descarga no comparte objetos con el modelo. Las no elegidas van sin enlace.
        elegidas = None if filas is None else set(filas)
        tracks = [dataclasses.replace(t) if elegidas is None or i in elegidas
                  else dataclasses.replace(t, youtube_url="")
                  for i, t in enumerate(self.model.tracks)]
        n = sum(bool(t.youtube_url) for t in tracks)
        if self.ocupado or not n:
            return
        dlg = DialogoDescarga(n, Path(self.ajustes["audio_dir"]), self.nombre_lista or "Lista de canciones",
                              self.ajustes["audio_format"], ffmpeg_disponible(), self, tracks=tracks)
        if not dlg.exec():
            return
        self.ajustes["audio_format"] = dlg.formato_elegido()
        self.ajustes["audio_dir"] = str(dlg.salida)   # «Cambiar…» en el diálogo la recuerda
        self.btn_archivo.setVisible(False)
        self.model.limpiar_audio()
        self._lanzar(DownloadWorker(self.ajustes.snapshot(), tracks, dlg.salida / dlg.carpeta(),
                                    album=self.nombre_lista, origen=self.origen_lista,
                                    mover_quitadas=dlg.mover_quitadas()), guardar=False)

    # Actualizar una descarga (sincronizar) ───────────────────────────────────

    def _actualizar_descarga(self, carpeta: Path | None = None):
        """
        Vuelve a extraer la playlist de una carpeta ya descargada (su enlace está
        en el manifiesto), busca solo las canciones nuevas y descarga en esa
        carpeta con su formato: lo ya descargado se renumera, no se repite.
        """
        if self.ocupado:
            return
        if carpeta is None:
            elegida = QFileDialog.getExistingDirectory(self, "Actualizar descarga", self.ajustes["audio_dir"])
            if not elegida:
                return
            carpeta = Path(elegida)
        if not carpeta.is_dir():
            self.lbl_fase.setText(f"La carpeta «{carpeta}» ya no existe")
            return
        manifiesto = leer_manifiesto(carpeta)
        origen = (manifiesto or {}).get("origen", "")
        src = parse_source(origen) if origen else None
        if src is None:
            QMessageBox.information(
                self, "Actualizar descarga",
                f"«{carpeta.name}» no se descargó con la app o no tiene enlace de Spotify "
                f"(no hay {ARCHIVO_MANIFIESTO} o no guarda el enlace de la lista).\n\n"
                "Usa Convertir + Descargar audio para descargarla.")
            return
        mover = self._confirmar_actualizacion(carpeta, manifiesto)
        if mover is None:
            return
        self._cambiar_modo(0)
        self.url.setText(src.url)
        self._nueva_lista(origen=src.url)
        self._lanzar(Worker(self.ajustes.snapshot(), url=src.url, manifiesto=manifiesto,
                            sync_folder=carpeta, mover_quitadas=mover))

    def _confirmar_actualizacion(self, carpeta: Path, manifiesto: dict) -> bool | None:
        """Pregunta antes de actualizar. None = cancelar; si no, si mover las quitadas a «Quitadas»."""
        from ..download import CARPETA_QUITADAS

        nombre = manifiesto.get("nombre") or carpeta.name
        caja = QMessageBox(QMessageBox.Question, "Actualizar descarga",
                           f"Actualizar «{nombre}» en\n{carpeta}\n\n"
                           "Se vuelve a leer la playlist de Spotify, se buscan en YouTube solo las "
                           "canciones nuevas y se descargan; las que ya están se renumeran si han "
                           "cambiado de posición.",
                           QMessageBox.Cancel, self)
        aceptar = caja.addButton("Actualizar", QMessageBox.AcceptRole)
        caja.setDefaultButton(aceptar)
        casilla = QCheckBox(f"Mover a «{CARPETA_QUITADAS}» las canciones que ya no están en la lista")
        caja.setCheckBox(casilla)
        caja.exec()
        if caja.clickedButton() is not aceptar:
            return None
        return casilla.isChecked()

    def _descargar_sincronizacion(self, w: Worker):
        """Tras la conversión de «Actualizar descarga»: descarga en su carpeta sin pasar por el diálogo."""
        from ..download import FORMATOS_AUDIO

        formato = (w.manifiesto or {}).get("formato")
        if formato not in FORMATOS_AUDIO:
            formato = self.ajustes["audio_format"]
        nombre = self.nombre_lista or (w.manifiesto or {}).get("nombre") or w.sync_folder.name
        # Como con el botón: se descargan las que tienen enlace (también las dudosas)
        tracks = [dataclasses.replace(t) for t in self.model.tracks]
        self.model.limpiar_audio()
        d = DownloadWorker(self.ajustes.snapshot(), tracks, w.sync_folder, album=nombre, origen=w.url,
                           mover_quitadas=w.mover_quitadas, formato=formato)
        d.dudosas = sum(t.status == Status.DOUBTFUL for t in tracks)
        self._lanzar(d, guardar=False)

    # Recientes ───────────────────────────────────────────────────────────────

    def _construir_menu_recientes(self):
        menu = self.menu_recientes
        menu.clear()
        for sub in menu.findChildren(QMenu):   # clear() no borra los submenús de la vez anterior
            sub.deleteLater()
        recientes = self.ajustes.recientes()
        libre = not self.ocupado
        if not recientes:
            menu.addAction("(sin listas recientes)").setEnabled(False)
        for r in recientes:
            texto = texto_reciente(r)
            if r["carpeta"]:
                sub = menu.addMenu(texto)
                sub.setToolTip(r["url"])
                sub.addAction("Convertir de nuevo", lambda r=r: self._abrir_reciente(r)).setEnabled(libre)
                sub.addAction("⟳  Actualizar descarga", lambda r=r: self._actualizar_descarga(Path(r["carpeta"]))
                              ).setEnabled(libre)
                sub.addAction("Abrir carpeta", lambda r=r: self._abrir_carpeta_reciente(r))
            else:
                a = menu.addAction(texto, lambda r=r: self._abrir_reciente(r))
                a.setToolTip(r["url"])
                a.setEnabled(libre)
        menu.addSeparator()
        menu.addAction("⟳  Actualizar una descarga…", lambda: self._actualizar_descarga()).setEnabled(libre)
        menu.addAction("Borrar recientes", self._borrar_recientes).setEnabled(bool(recientes))
        menu.setToolTipsVisible(True)

    def _abrir_reciente(self, r: dict):
        if self.ocupado:
            return
        self._cambiar_modo(0)
        self.url.setText(r["url"])
        self._convertir()

    def _abrir_carpeta_reciente(self, r: dict):
        carpeta = Path(r["carpeta"])
        if carpeta.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(carpeta)))
        else:
            self.lbl_fase.setText(f"La carpeta «{carpeta}» ya no existe")

    def _borrar_recientes(self):
        self.ajustes.borrar_recientes()
        self.lbl_fase.setText("Lista de recientes borrada")

    # Abrir un .csv ───────────────────────────────────────────────────────────

    def _abrir_csv(self, ruta: Path | None = None):
        """
        Carga un .csv (de esta app o de Exportify) en la tabla. Las canciones que
        traen enlace lo conservan; si ninguna lo trae (Exportify), se buscan todas.
        """
        if self.ocupado:
            return
        if ruta is None:
            elegido, _ = QFileDialog.getOpenFileName(self, "Abrir .csv", self.ajustes["out_dir"], IMPORTABLES["csv"])
            if not elegido:
                return
            ruta = Path(elegido)
        try:
            nombre, tracks = from_csv(ruta)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Abrir .csv", f"No se pudo abrir «{ruta.name}».\n\n{e}")
            return
        if not tracks:
            QMessageBox.warning(self, "Abrir .csv", f"«{ruta.name}» no contiene canciones.")
            return
        self._cambiar_modo(1)
        self.texto.clear()
        self._nueva_lista(tracks, nombre=nombre)
        self._log(f"Lista: {nombre} ({plural(len(tracks), 'canción', 'canciones')} de {ruta.name})")
        faltan = [i for i, t in enumerate(tracks) if t.status in (Status.PENDING, Status.FAILED)]
        if faltan and not any(t.youtube_url for t in tracks):
            self._buscar_filas(faltan, use_cache=True, guardar=True)   # Exportify: como una conversión
            return
        texto = f"Cargadas {plural(len(tracks), 'canción', 'canciones')} de {ruta.name}"
        if faltan:
            texto += f" · {len(faltan)} sin enlace: pulsa «Reintentar fallidas» para buscarlas"
        self.lbl_fase.setText(texto)

    def _exportar(self, ext: str):
        if self.ocupado:
            return
        carpeta = Path(self.ajustes["out_dir"])
        try:
            carpeta.mkdir(parents=True, exist_ok=True)   # el diálogo abre ahí (p. ej. enlaces/ aún sin crear)
        except OSError:
            pass
        inicial = str(carpeta / default_name(ext, self.nombre_lista))
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar", inicial, FORMATOS[ext])
        if not ruta:
            return
        try:
            n = export(self.model.tracks, Path(ruta))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Exportar", str(e))
            return
        self.ultima_carpeta = Path(ruta).parent
        self.ajustes["out_dir"] = str(Path(ruta).parent)
        self.lbl_fase.setText(f"{'Exportada' if n == 1 else 'Exportadas'} {plural(n, 'fila', 'filas')} a {Path(ruta).name}")
        self.btn_archivo.setVisible(True)

    def _abrir_carpeta(self):
        if self.ultima_carpeta:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ultima_carpeta)))

    def _abrir_ajustes(self):
        DialogoAjustes(self.ajustes, self).exec()

    def _texto_tema(self):
        self.btn_tema.setText("☀  Claro" if self.ajustes["theme"] == "dark" else "☾  Oscuro")

    def _cambiar_tema(self):
        self.ajustes["theme"] = "light" if self.ajustes["theme"] == "dark" else "dark"
        aplicar_tema(QApplication.instance(), self.ajustes["theme"])
        self.model.set_tema(self.ajustes["theme"])
        self._texto_tema()
        self._refrescar()   # los chips llevan el color en su HTML

    def closeEvent(self, event):
        if self.ocupado:
            # Nunca destruir un QThread en marcha: se cancela y se cierra en _on_fin
            if not self._cerrar_al_terminar:
                r = QMessageBox.question(self, "Salir", "Hay una conversión/descarga en curso. ¿Cancelar y salir?")
                if r != QMessageBox.Yes:
                    event.ignore()
                    return
                self._cerrar_al_terminar = True
                self.worker.cancel.set()
                self.btn_cancelar.setEnabled(False)
                self.lbl_fase.setText("Cancelando para salir…")
            event.ignore()
            return
        self._guardar_estado_ui()
        esperar_busquedas()   # búsquedas de «Elegir otra versión» de diálogos ya cerrados
        super().closeEvent(event)
