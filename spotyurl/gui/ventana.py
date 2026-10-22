"""Ventana principal."""

import dataclasses
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox,
    QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QStackedWidget, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from ..export import FORMATOS, default_name, export, to_txt, unique_path
from ..models import Status
from ..paths import safe_filename
from ..spotify import parse_source, parse_text_list
from .ajustes import Ajustes
from .constantes import COLOR_ESTADO, ICON_PATH
from .dialogo_ajustes import DialogoAjustes
from .modelo import FiltroTracks, TrackTableModel
from .tema import aplicar_tema, repolish
from .workers import DownloadWorker, Worker


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
        self.nombre_lista = ""   # nombre de la playlist/álbum ("" en «Lista de texto»)
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
        # Cmd+, en macOS (en Windows no hay atajo estándar y no hace nada)
        preferencias = QAction(self, shortcut=QKeySequence(QKeySequence.Preferences))
        preferencias.triggered.connect(self._abrir_ajustes)
        self.addAction(preferencias)

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
        borrar = QAction(self.tabla, shortcutContext=Qt.WidgetShortcut)
        # En el teclado de Mac la tecla "delete" es Backspace
        borrar.setShortcuts([QKeySequence(QKeySequence.Delete), QKeySequence(Qt.Key_Backspace)])
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
        self.btn_descargar = QPushButton("⬇  Descargar audio")
        self.btn_descargar.setToolTip("Descarga el audio de las canciones con enlace a una carpeta")
        self.btn_descargar.clicked.connect(self._descargar)
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
        h.addWidget(self.btn_descargar)
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
        self.btn_descargar.setEnabled(con_enlace and not self.ocupado)
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
        self.nombre_lista = ""
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
        w.name_found.connect(self._on_nombre)
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

    def _on_nombre(self, nombre: str):
        self.nombre_lista = nombre.strip()
        if self.nombre_lista:
            self._log(f"Lista: {self.nombre_lista}")

    def _on_error(self, msg: str):
        self._log(msg)
        QMessageBox.warning(self, "No se pudo completar", msg)

    def _on_fin(self, w: Worker, guardar: bool):
        cancelado = w.cancel.is_set()
        self.worker = None
        w.deleteLater()
        self._set_ocupado(False)
        if isinstance(w, DownloadWorker):
            # Ni mensaje de conversión ni auto-guardado del .txt tras una descarga
            self._fin_descarga(w, cancelado)
            return
        tracks = self.model.tracks
        n_links = sum(bool(t.youtube_url) for t in tracks)
        estado = "Cancelado" if cancelado else "Listo"
        titulo = f"«{self.nombre_lista}» · " if self.nombre_lista else ""
        self.lbl_fase.setText(f"{estado}: {titulo}{n_links} de {len(tracks)} canciones con enlace")
        if guardar and n_links and w.opts["auto_save"] and not cancelado:
            carpeta = Path(self.ajustes["out_dir"])
            try:
                carpeta.mkdir(parents=True, exist_ok=True)
                # unique_path: no sobrescribir el .txt de una conversión anterior de la misma lista
                self.ultimo_archivo = unique_path(carpeta / default_name("txt", self.nombre_lista))
                to_txt(tracks, self.ultimo_archivo)
                self._log(f"Guardado: {self.ultimo_archivo}")
                self.lbl_fase.setText(self.lbl_fase.text() + f"  ·  {self.ultimo_archivo.name}")
                self.btn_archivo.setVisible(True)
            except OSError as e:
                self._log(f"No se pudo guardar el .txt: {e}")

    def _fin_descarga(self, w: DownloadWorker, cancelado: bool):
        r = w.result
        if r is None:   # el error ya se avisó con la señal failed
            self.lbl_fase.setText("La descarga no se pudo completar")
            return
        for t, motivo in r.failed:
            self._log(f"No se pudo descargar «{t.label}»: {motivo}")
        resumen = f"Descargadas {len(r.ok)} · ya existían {len(r.skipped)} · fallidas {len(r.failed)}"
        self.lbl_fase.setText(f"Cancelado: {resumen}" if cancelado else resumen)
        self._log(resumen)
        # _mostrar_archivo abre ultimo_archivo.parent: apuntar a algo dentro de la carpeta
        self.ultimo_archivo = w.folder / "_"
        self.btn_archivo.setVisible(w.folder.is_dir())

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

    def _descargar(self):
        from ..download import ffmpeg_disponible

        # Copias de toda la lista (la numeración 01, 02… sigue la posición en la
        # playlist); el hilo de descarga no comparte objetos con el modelo
        tracks = [dataclasses.replace(t) for t in self.model.tracks]
        n = sum(bool(t.youtube_url) for t in tracks)
        if self.ocupado or not n:
            return
        salida = Path(self.ajustes["audio_dir"])
        sin_ffmpeg = not ffmpeg_disponible()
        aviso = (
            "\n\nffmpeg no está instalado: el audio se guardará en .m4a/.webm.\n"
            "Instálalo para obtener .mp3."
        ) if sin_ffmpeg else ""
        nombre, ok = QInputDialog.getText(
            self, "Descargar audio",
            f"Se descargarán {n} canciones en una carpeta nueva dentro de:\n{salida}\n"
            f"(puedes cambiarla en Ajustes → Carpeta de audio){aviso}\n\nNombre de la carpeta:",
            QLineEdit.Normal, self.nombre_lista or "Lista de canciones",
        )
        if not ok:
            return
        nombre = safe_filename(nombre)
        if not nombre:
            QMessageBox.warning(self, "Descargar audio", "El nombre de la carpeta no es válido.")
            return
        self.btn_archivo.setVisible(False)
        self._lanzar(DownloadWorker(self.ajustes.snapshot(), tracks, salida / nombre), guardar=False)

    def _exportar(self, ext: str):
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
