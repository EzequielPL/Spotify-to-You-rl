"""Pruebas de la interfaz gráfica sin pantalla (QT_QPA_PLATFORM=offscreen)."""

import dataclasses
import os
import threading

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from spotyurl.models import Status, Track  # noqa: E402

ENLACE = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ajustes(tmp_path):
    from spotyurl.gui import Ajustes

    return Ajustes(QSettings(str(tmp_path / "ajustes.ini"), QSettings.IniFormat))


@pytest.fixture
def ventana(app, ajustes):
    from spotyurl.gui import MainWindow

    w = MainWindow(ajustes)
    yield w
    w.worker = None
    w.close()


# ── Textos ───────────────────────────────────────────────────────────────────

def test_plural():
    from spotyurl.gui.constantes import plural

    assert plural(1, "canción", "canciones") == "1 canción"
    assert plural(0, "canción", "canciones") == "0 canciones"
    assert plural(2, "dudosa") == "2 dudosas"


def test_chips_y_estado_sin_enlace(ventana):
    assert not any(c.isVisibleTo(ventana) for c in ventana.chips.values())   # tabla vacía: sin chips
    ventana.model.set_tracks([Track(title="A", status=Status.FAILED), Track(title="B", status=Status.OK,
                                                                             youtube_url="https://youtu.be/x")])
    assert all(c.isVisibleTo(ventana) for c in ventana.chips.values())
    assert "1 sin enlace" in ventana.chips[Status.FAILED].text()
    assert "1 encontrada" in ventana.chips[Status.OK].text() and "encontradas" not in ventana.chips[Status.OK].text()
    m = ventana.model
    assert m.data(m.index(0, m.COL_ESTADO)) == "●  sin enlace"


def test_ayuda_lista_de_texto_singular(ventana):
    ventana._cambiar_modo(1)
    ventana.texto.setPlainText("Rosalía - Despechá")
    assert ventana.lbl_ayuda.text() == "1 canción"


# ── Colores por tema ─────────────────────────────────────────────────────────

def _contraste(a: str, b: str) -> float:
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    x, y = sorted((lum(a), lum(b)))
    return (y + 0.05) / (x + 0.05)


@pytest.mark.parametrize("tema", ["light", "dark"])
def test_colores_estado_legibles(tema):
    from spotyurl.gui.tema import PALETAS, colores_estado

    colores = colores_estado(tema)
    assert set(colores) == set(Status)
    for fondo in ("card", "alt", "input"):
        for estado, color in colores.items():
            assert _contraste(color, PALETAS[tema][fondo]) >= 4.5, (tema, estado, fondo)


def test_modelo_cambia_color_con_el_tema(ventana):
    from spotyurl.gui.tema import colores_estado

    m = ventana.model
    m.set_tracks([Track(title="A", status=Status.OK)])
    cambios = []
    m.dataChanged.connect(lambda *a: cambios.append(a))
    tema_antes = ventana.ajustes["theme"]
    ventana._cambiar_tema()
    tema = ventana.ajustes["theme"]
    assert tema != tema_antes and cambios
    assert m.data(m.index(0, m.COL_ESTADO), Qt.ForegroundRole) == QColor(colores_estado(tema)[Status.OK])
    assert colores_estado(tema)[Status.OK] in ventana.chips[Status.OK].text()


# ── Arrastrar y soltar ───────────────────────────────────────────────────────

def _soltar(w, mime):
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    w.dropEvent(ev)
    return ev


def test_soltar_enlace_rellena_y_convierte(ventana):
    llamadas = []
    ventana._convertir = lambda: llamadas.append(ventana.url.text())   # sin lanzar Playwright
    ventana._cambiar_modo(1)
    mime = QMimeData()
    mime.setText(f"Escucha esto: {ENLACE}?si=abc")
    _soltar(ventana, mime)
    assert ventana.modo == 0
    assert ventana.url.text() == ENLACE
    assert llamadas == [ENLACE]
    assert ventana.tarjeta_entrada.property("drop") is False


def test_soltar_txt_pasa_a_lista_de_texto(ventana, tmp_path):
    archivo = tmp_path / "lista.txt"
    archivo.write_bytes("Bruno Mars - Locked Out of Heaven\nRosalía - Despechá\n".encode("utf-8") + b"\xff\n")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(archivo))])
    _soltar(ventana, mime)
    assert ventana.modo == 1
    assert "Rosalía - Despechá" in ventana.texto.toPlainText()
    assert ventana.lbl_ayuda.text() == "2 canciones"


def test_soltar_otra_cosa_no_hace_nada(ventana):
    mime = QMimeData()
    mime.setText("hola")
    _soltar(ventana, mime)
    assert ventana.url.text() == ""


# ── B4: nombre del .txt auto-guardado ────────────────────────────────────────

def test_autoguardado_sobrescribe_misma_lista(tmp_path):
    from spotyurl.gui.ventana import ruta_autoguardado

    primera = ruta_autoguardado(tmp_path, "Mi lista: 2024")
    primera.write_text("x")
    assert ruta_autoguardado(tmp_path, "Mi lista: 2024") == primera
    sin_nombre = ruta_autoguardado(tmp_path, "")
    assert sin_nombre.name.startswith("youtube_links_") and not sin_nombre.exists()


# ── B3: al portapapeles solo las seguras ─────────────────────────────────────

def test_portapapeles_no_copia_dudosas(monkeypatch):
    from spotyurl import youtube
    from spotyurl.gui import DEFAULTS, Worker

    class Falso:
        def __init__(self, **kw):
            pass

        def match(self, t, cancel, use_cache=True):
            t.youtube_url = f"https://www.youtube.com/watch?v={t.title:_<11}"
            t.status = Status.DOUBTFUL if t.title == "dudosa" else Status.OK

        def save_cache(self):
            pass

    monkeypatch.setattr(youtube, "YouTubeMatcher", Falso)
    opts = dict(DEFAULTS, clipboard=True, pause=0, use_cache=False)
    w = Worker(opts, items=[(0, Track(title="buena")), (1, Track(title="dudosa"))])
    copiados = []
    w.copy_request.connect(copiados.append)
    w._buscar()
    assert len(copiados) == 1 and "buena" in copiados[0]


# ── Cierre y estado persistente ──────────────────────────────────────────────

def test_cerrar_sin_trabajo_guarda_estado(app, ajustes):
    from spotyurl.gui import MainWindow

    w = MainWindow(ajustes)
    w._cambiar_modo(1)
    w.btn_log.setChecked(True)
    assert w.close()
    assert ajustes.get_bytes("ui/geometry") is not None
    assert ajustes.get_bytes("ui/header") is not None
    w2 = MainWindow(ajustes)
    assert w2.modo == 1 and w2.seg_texto.isChecked() and w2.btn_log.isChecked()
    w2.close()


class _WorkerFalso:
    errores = 0

    def __init__(self):
        self.cancel = threading.Event()
        self.corriendo = True

    def isRunning(self):
        return self.corriendo

    def deleteLater(self):
        pass


def test_cerrar_con_trabajo_pregunta_y_espera(app, ajustes, monkeypatch):
    from spotyurl.gui import MainWindow

    w = MainWindow(ajustes)
    w.show()
    falso = _WorkerFalso()
    w.worker = falso
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    assert not w.close()
    assert not falso.cancel.is_set()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    assert not w.close()                 # no se cierra con el hilo en marcha
    assert falso.cancel.is_set() and w._cerrar_al_terminar and w.isVisible()

    falso.corriendo = False              # el hilo termina
    w._on_fin(falso, guardar=False)
    app.processEvents()
    assert not w.isVisible()


def test_ocupado_desactiva_acciones(ventana):
    ventana.model.set_tracks([Track(title="A", status=Status.OK, youtube_url="https://youtu.be/x")])
    ventana.worker = _WorkerFalso()
    ventana._set_ocupado(True)
    assert not ventana.btn_copiar.isEnabled() and not ventana.btn_exportar.isEnabled()
    assert not ventana.btn_descargar.isEnabled()
    m = ventana.model
    assert not m.flags(m.index(0, m.COL_ENLACE)) & Qt.ItemIsEditable
    ventana.worker = None
    ventana._set_ocupado(False)
    assert ventana.btn_copiar.isEnabled() and m.flags(m.index(0, m.COL_ENLACE)) & Qt.ItemIsEditable


def test_enlace_no_youtube_avisa(ventana):
    ventana.model.set_tracks([Track(title="A")])
    m = ventana.model
    assert not m.setData(m.index(0, m.COL_ENLACE), "https://example.com/x")
    assert "no es un enlace de YouTube" in ventana.lbl_fase.texto_completo()


# ── Ajustes ──────────────────────────────────────────────────────────────────

def test_dialogo_ajustes_portapapeles(app, ajustes):
    from spotyurl.gui import DEFAULTS, DialogoAjustes

    assert DEFAULTS["clipboard"] is False
    d = DialogoAjustes(ajustes)
    assert [g.title() for g in d.grupos] == ["Carpetas", "Portapapeles (MediaHuman)", "Búsqueda", "Avanzado",
                                         "Mantenimiento"]
    assert not d.clip.isChecked() and not d.pausa.isEnabled()
    d.clip.setChecked(True)
    d.pausa.setValue(2.5)
    d.accept()
    assert ajustes["clipboard"] is True and ajustes["pause"] == 2.5


# ── F2 / B2: elegir otra versión y correcciones persistentes ─────────────────

def _cands():
    from spotyurl.youtube import Candidate

    return [Candidate("aaaaaaaaaaa", "Canción (Official)", "Artista - Topic", 200, 0.9),
            Candidate("bbbbbbbbbbb", "Canción (Live)", "Otro", 215, 0.3)]


@pytest.fixture
def recordadas(monkeypatch):
    from spotyurl import youtube

    llamadas = []
    monkeypatch.setattr(youtube, "recordar_eleccion",
                        lambda ruta, t: llamadas.append((t.youtube_url, t.status)))
    return llamadas


def _dudosa(titulo="T", **kw):
    c = _cands()
    datos = dict(title=titulo, artists=["A"], duration_s=200, status=Status.DOUBTFUL,
                 youtube_url=c[1].url, youtube_title=c[1].title, score=c[1].score, candidates=c)
    datos.update(kw)
    return Track(**datos)


def test_usar_candidato_actualiza_fila_y_recuerda(ventana, recordadas):
    ventana.model.set_tracks([_dudosa()])
    c = _cands()
    ventana._usar_candidato(0, c[0])
    t = ventana.model.tracks[0]
    assert (t.youtube_url, t.youtube_title, t.score, t.status) == (c[0].url, c[0].title, 0.9, Status.MANUAL)
    assert len(t.candidates) == 2
    assert recordadas == [(c[0].url, Status.MANUAL)]


def test_sin_cache_no_recuerda(ventana, recordadas):
    ventana.ajustes["use_cache"] = False
    ventana.model.set_tracks([_dudosa()])
    ventana._usar_candidato(0, _cands()[0])
    assert recordadas == []


def test_enlace_pegado_o_borrado_se_recuerda(ventana, recordadas):
    ventana.model.set_tracks([_dudosa()])
    m = ventana.model
    assert m.setData(m.index(0, m.COL_ENLACE), "https://youtu.be/aaaaaaaaaaa")
    assert m.tracks[0].youtube_title == "Canción (Official)"   # era un candidato conocido
    assert m.setData(m.index(0, m.COL_ENLACE), "")
    assert recordadas == [("https://www.youtube.com/watch?v=aaaaaaaaaaa", Status.MANUAL), ("", Status.FAILED)]


def test_elegir_version_con_filtro_dudosas_selecciona_la_siguiente(ventana, recordadas, monkeypatch):
    from spotyurl.gui import ventana as mod

    class DialogoFalso:
        SALTAR = 2

        def __init__(self, track, opts, tema, revision=False, parent=None):
            self.elegido, self.candidatos = track.candidates[0], track.candidates

        def exec(self):
            return mod.QDialog.Accepted

    monkeypatch.setattr(mod, "DialogoCandidatos", DialogoFalso)
    ventana.model.set_tracks([_dudosa("uno"), Track(title="ok", status=Status.OK), _dudosa("dos"), _dudosa("tres")])
    ventana.filtro_estado.setCurrentIndex(mod.FILTRO_DUDOSAS)
    ventana._seleccionar_fila_proxy(0)
    assert ventana._fila_actual() == 0
    ventana.accion_elegir.trigger()   # Ctrl+E
    assert ventana.model.tracks[0].status == Status.MANUAL
    assert ventana._fila_actual() == 2   # la siguiente dudosa queda seleccionada
    assert len(recordadas) == 1


def test_revisar_dudosas_recorre_y_salta(ventana, recordadas, monkeypatch):
    from spotyurl.gui import ventana as mod

    respuestas = iter([2, mod.QDialog.Accepted, mod.QDialog.Rejected])
    vistas = []

    class DialogoFalso:
        SALTAR = 2

        def __init__(self, track, opts, tema, revision=False, parent=None):
            assert revision
            vistas.append(track.title)
            self.elegido, self.candidatos = track.candidates[0], track.candidates

        def exec(self):
            return next(respuestas)

    monkeypatch.setattr(mod, "DialogoCandidatos", DialogoFalso)
    ventana.model.set_tracks([_dudosa("uno"), _dudosa("dos"), _dudosa("tres")])
    ventana._revisar_dudosas()
    assert vistas == ["uno", "dos", "tres"]   # salta «uno», usa «dos», cierra en «tres»
    assert [t.status for t in ventana.model.tracks] == [Status.DOUBTFUL, Status.MANUAL, Status.DOUBTFUL]


def test_dialogo_candidatos_muestra_diferencia_y_actual(app):
    from spotyurl.gui import DialogoCandidatos
    from spotyurl.gui.dialogo_candidatos import diferencia_duracion

    assert diferencia_duracion(205, 200) == "+0:05"
    assert diferencia_duracion(188, 200) == "−0:12"
    assert diferencia_duracion(None, 200) == ""
    d = DialogoCandidatos(_dudosa(), {"n_results": 6, "query_template": "{artist} - {title}"})
    assert d.tabla.rowCount() == 2 and d.worker is None
    assert d.tabla.item(1, 0).text().startswith("●")          # el actual (el segundo) resaltado
    assert "(+0:15)" in d.tabla.item(1, 2).text()
    assert d.tabla.selectionModel().selectedRows()[0].row() == 1
    d.tabla.selectRow(0)
    d._usar()
    assert d.result() == DialogoCandidatos.Accepted and d.elegido.id == "aaaaaaaaaaa"


def test_dialogo_candidatos_busca_en_un_hilo(app, monkeypatch):
    from spotyurl import youtube
    from spotyurl.gui import DialogoCandidatos

    class Falso:
        def __init__(self, **kw):
            pass

        def candidates(self, track, cancel=None):
            return _cands()

    monkeypatch.setattr(youtube, "YouTubeMatcher", Falso)
    d = DialogoCandidatos(Track(title="T", artists=["A"], duration_s=200), {"n_results": 6, "query_template": "x"})
    assert "Buscando" in d.lbl_estado.text() and not d.btn_usar.isEnabled()
    assert d.worker.wait(5000)
    app.processEvents()
    assert d.tabla.rowCount() == 2 and len(d.candidatos) == 2 and d.btn_usar.isEnabled()


def test_worker_propaga_candidatos(monkeypatch):
    from spotyurl import youtube
    from spotyurl.gui import DEFAULTS, Worker

    class Falso:
        def __init__(self, **kw):
            pass

        def match(self, t, cancel, use_cache=True):
            t.candidates = _cands()
            t.youtube_url, t.status = t.candidates[0].url, Status.OK

        def save_cache(self):
            pass

    monkeypatch.setattr(youtube, "YouTubeMatcher", Falso)
    w = Worker(dict(DEFAULTS, use_cache=False), items=[(0, Track(title="T"))])
    emitidas = []
    w.track_updated.connect(lambda row, t: emitidas.append(t))
    w._buscar()
    assert emitidas[0].status == Status.SEARCHING and len(emitidas[-1].candidates) == 2


# ── U5: ordenar, marcar, descargar seleccionadas, chips ──────────────────────

def _orden_visible(ventana, col, rol=Qt.DisplayRole):
    p = ventana.proxy
    return [p.data(p.index(i, col), rol) for i in range(p.rowCount())]


def test_orden_numerico_de_numero_y_duracion(ventana):
    from spotyurl.gui import TrackTableModel as M

    dur = [600, 59, 125] + [100] * 9
    ventana.model.set_tracks([Track(title=f"t{i}", duration_s=d) for i, d in enumerate(dur)])
    ventana.tabla.sortByColumn(M.COL_NUM, Qt.DescendingOrder)
    assert _orden_visible(ventana, M.COL_NUM)[:3] == [12, 11, 10]
    ventana.tabla.sortByColumn(M.COL_DURACION, Qt.AscendingOrder)
    assert _orden_visible(ventana, M.COL_DURACION)[0] == "0:59"
    assert _orden_visible(ventana, M.COL_DURACION)[-1] == "10:00"   # como texto quedaría antes que 2:05


def test_orden_por_estado_y_filas_mapeadas(ventana):
    from spotyurl.gui import TrackTableModel as M

    ventana.model.set_tracks([Track(title="ok", status=Status.OK), Track(title="sin", status=Status.FAILED),
                              _dudosa("dudosa")])
    ventana.tabla.sortByColumn(M.COL_ESTADO, Qt.AscendingOrder)
    assert _orden_visible(ventana, M.COL_TITULO) == ["dudosa", "sin", "ok"]
    ventana._seleccionar_fila_proxy(0)
    assert ventana._filas_seleccionadas() == [2]   # fila del modelo, no de la vista


def test_marcar_como_correcta(ventana, recordadas):
    ventana.model.set_tracks([_dudosa(), Track(title="sin", status=Status.FAILED),
                              Track(title="ok", status=Status.OK, youtube_url="https://youtu.be/x")])
    assert [ventana._se_puede_marcar(r) for r in range(3)] == [True, False, False]
    ventana._marcar_correctas([0, 1, 2])
    assert [t.status for t in ventana.model.tracks] == [Status.MANUAL, Status.FAILED, Status.OK]
    assert len(recordadas) == 1


def test_descargar_seleccionadas_vacia_las_demas(ventana, monkeypatch, tmp_path):
    from spotyurl.gui import ventana as mod

    class DialogoFalso:
        def __init__(self, n, salida, nombre, formato, con_ffmpeg, parent=None, tracks=None):
            self.n, self.salida = n, tmp_path

        def exec(self):
            return True

        def formato_elegido(self):
            return "mp3"

        def carpeta(self):
            return "Mi lista"

        def mover_quitadas(self):
            return True

    monkeypatch.setattr(mod, "DialogoDescarga", DialogoFalso)
    lanzados = []
    monkeypatch.setattr(ventana, "_lanzar", lambda w, guardar=True: lanzados.append(w))
    ventana.nombre_lista, ventana.origen_lista = "Mi lista", ENLACE
    ventana.model.set_tracks([Track(title=str(i), status=Status.OK, youtube_url=f"https://youtu.be/{i}")
                              for i in range(4)])
    ventana.model.set_audio(0, "ok", 100.0)
    ventana._descargar([1, 3])
    w = lanzados[0]
    assert [t.youtube_url for t in w.tracks] == ["", "https://youtu.be/1", "", "https://youtu.be/3"]
    assert w.album == "Mi lista" and w.folder == tmp_path / "Mi lista"
    assert w.origen == ENLACE and w.mover_quitadas is True
    assert ventana.model.audio == {}                       # se limpia el estado de la anterior
    assert ventana.model.tracks[0].youtube_url             # el modelo no se toca


def test_chip_clicable_cambia_el_filtro(ventana):
    from PySide6.QtTest import QTest

    from spotyurl.gui import ventana as mod

    ventana.model.set_tracks([_dudosa(), Track(title="ok", status=Status.OK)])
    chip = ventana.chips[Status.DOUBTFUL]
    QTest.mouseClick(chip, Qt.LeftButton)
    assert ventana.filtro_estado.currentIndex() == mod.FILTRO_DUDOSAS
    assert ventana.proxy.rowCount() == 1 and chip.property("activo") is True
    QTest.mouseClick(chip, Qt.LeftButton)
    assert ventana.filtro_estado.currentIndex() == mod.FILTRO_TODAS and ventana.proxy.rowCount() == 2


def test_cabecera_de_otra_version_no_se_restaura(app, ajustes):
    from PySide6.QtGui import QStandardItemModel
    from PySide6.QtWidgets import QTableView

    from spotyurl.gui import MainWindow
    from spotyurl.gui.ventana import ANCHOS_COLUMNAS

    vieja = QTableView()
    vieja.setModel(QStandardItemModel(0, 6))
    vieja.setColumnWidth(1, 777)
    ajustes.set_bytes("ui/header", vieja.horizontalHeader().saveState())   # versión anterior: 6 columnas
    w = MainWindow(ajustes)
    assert w.tabla.columnWidth(1) == ANCHOS_COLUMNAS[1]
    w.tabla.setColumnWidth(1, 333)
    w.close()
    assert ajustes["header_cols"] == w.model.columnCount()
    w2 = MainWindow(ajustes)
    assert w2.tabla.columnWidth(1) == 333   # la guardada con las columnas actuales sí se restaura
    w2.close()


# ── U3: progreso de la descarga ──────────────────────────────────────────────

def test_columna_audio_estados_y_motivo(ventana):
    m = ventana.model
    M = type(m)
    m.set_tracks([Track(title=str(i)) for i in range(3)])
    assert ventana.tabla.isColumnHidden(M.COL_AUDIO)
    textos = {}
    for estado, pct in [("cola", 0), ("descargando", 45.4), ("convirtiendo", 100), ("etiquetando", 100),
                        ("ok", 100), ("existe", 100), ("error", 0)]:
        m.set_audio(1, estado, pct)
        textos[estado] = m.data(m.index(1, M.COL_AUDIO))
    assert textos == {"cola": "en cola", "descargando": "⬇ 45 %", "convirtiendo": "convirtiendo…",
                      "etiquetando": "etiquetando…", "ok": "✓", "existe": "ya existía", "error": "✗"}
    assert not ventana.tabla.isColumnHidden(M.COL_AUDIO)
    m.set_motivo_audio(1, "HTTP Error 403: Forbidden")
    assert "403" in m.data(m.index(1, M.COL_AUDIO), Qt.ToolTipRole)
    m.remove_rows([0])                              # las filas siguientes suben
    assert m.audio == {0: ("error", 0)} and "403" in m.data(m.index(0, M.COL_AUDIO), Qt.ToolTipRole)
    m.set_tracks([Track(title="nueva")])            # otra lista: se limpia
    assert m.audio == {} and m.motivos_audio == {}
    assert ventana.tabla.isColumnHidden(M.COL_AUDIO)


def test_fin_descarga_pone_el_motivo_en_la_fila(ventana, monkeypatch, tmp_path):
    from spotyurl.download import DownloadResult
    from spotyurl.gui import DEFAULTS, DownloadWorker

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    ventana.model.set_tracks([Track(title="a", youtube_url="https://youtu.be/a"),
                              Track(title="b", youtube_url="https://youtu.be/b")])
    copias = [Track(title="a"), Track(title="b")]
    w = DownloadWorker(dict(DEFAULTS), copias, tmp_path)
    w.result = DownloadResult(failed=[(copias[1], "Video unavailable")])
    ventana.model.set_audio(1, "error")
    ventana._fin_descarga(w, False)
    m = ventana.model
    assert "Video unavailable" in m.data(m.index(1, m.COL_AUDIO), Qt.ToolTipRole)


def test_download_worker_emite_estados_y_album(monkeypatch, tmp_path):
    from spotyurl import download
    from spotyurl.gui import DEFAULTS, DownloadWorker

    recibido = {}

    def falso(tracks, folder, on_progress=None, on_log=None, cancel=None, formato="mp3", album="", on_track=None,
              origen="", mover_quitadas=False, lista_m3u=True):
        recibido.update(album=album, origen=origen, mover_quitadas=mover_quitadas, formato=formato)
        on_track(1, "descargando", 50.0)
        on_track(1, "ok", 100.0)
        return download.DownloadResult(ok=[tracks[1]])

    monkeypatch.setattr(download, "download_tracks", falso)
    w = DownloadWorker(dict(DEFAULTS, audio_format="m4a"), [Track(title="a"), Track(title="b", youtube_url="u")],
                       tmp_path, album="Lista", origen=ENLACE, mover_quitadas=True)
    estados = []
    w.audio_estado.connect(lambda i, e, p: estados.append((i, e, p)))
    w.run()
    assert recibido == {"album": "Lista", "origen": ENLACE, "mover_quitadas": True, "formato": "m4a"}
    assert estados == [(1, "descargando", 50.0), (1, "ok", 100.0)]


def test_texto_restante():
    from spotyurl.gui.ventana import texto_restante

    assert texto_restante(10) == "queda menos de 1 min"
    assert texto_restante(70) == "queda ~1 min"
    assert texto_restante(130) == "quedan ~2 min"
    assert texto_restante(3720) == "quedan ~1 h 02 min"


def test_linea_de_progreso_con_estimacion(ventana):
    ventana.model.set_tracks([Track(title=f"T{i}", artists=["A"], youtube_url="u") for i in range(3)])
    ventana._on_fase("Descargando audio…", 3)
    ventana._on_audio(0, "descargando", 0.0)
    assert ventana.lbl_fase.texto_completo() == "Descargando 1/3 · A – T0"   # sin estimación aún
    ventana._t_inicio -= 60                       # la primera tardó un minuto
    ventana._on_audio(0, "ok", 100.0)
    ventana._on_progreso(1)
    ventana._on_audio(1, "descargando", 0.0)
    assert ventana.lbl_fase.texto_completo() == "Descargando 2/3 · A – T1 · quedan ~2 min"
    ventana._on_fase("Buscando en YouTube…", 3)
    ventana._on_track_actualizado(0, Track(title="X", artists=["B"], status=Status.SEARCHING))
    assert ventana.lbl_fase.texto_completo() == "Buscando 1/3 · B – X"


def test_boton_cancelar_junto_a_la_barra(ventana):
    falso = _WorkerFalso()
    ventana.worker = falso
    ventana._set_ocupado(True)
    assert ventana.btn_cancelar.isVisibleTo(ventana) and not ventana.btn_convertir.isEnabled()
    assert not ventana.accion_elegir.isEnabled()
    ventana.btn_cancelar.click()
    assert falso.cancel.is_set() and ventana.lbl_fase.texto_completo() == "Cancelando…"
    ventana.worker = None
    ventana._set_ocupado(False)
    assert not ventana.btn_cancelar.isVisibleTo(ventana)


# ── F4: actualizar yt-dlp ────────────────────────────────────────────────────

def _esperar(cond, ms=30000):
    import time

    limite = time.monotonic() + ms / 1000
    while not cond():
        assert time.monotonic() < limite, "tiempo agotado"
        QApplication.processEvents()
        time.sleep(0.01)


def test_dialogo_actualizar_termina_y_habilita_cerrar(app):
    import sys

    from spotyurl.gui import DialogoActualizar

    d = DialogoActualizar(comando=[sys.executable, "-c", "print('todo ok')"],
                          comando_version=[sys.executable, "-c", "print('2099.01.01')"])
    assert not d.btn_cerrar.isEnabled() and not d.btn_reiniciar.isVisibleTo(d)
    _esperar(lambda: d.codigo is not None)
    assert d.ok and d.btn_cerrar.isEnabled()
    assert "todo ok" in d.salida.toPlainText()
    assert d.version_despues == "2099.01.01"
    assert "actualizado a 2099.01.01" in d.lbl_estado.text() and "Reinicia" in d.lbl_estado.text()
    assert d.btn_reiniciar.isVisibleTo(d)
    assert d.barra.maximum() == 1     # ya no es indeterminada
    d.close()


def test_dialogo_actualizar_fallo_muestra_codigo(app):
    import sys

    from spotyurl.gui import DialogoActualizar

    d = DialogoActualizar(comando=[sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"],
                          comando_version=[sys.executable, "-c", "raise SystemExit(1)"])
    _esperar(lambda: d.codigo is not None)
    assert not d.ok and d.codigo == 3 and d.btn_cerrar.isEnabled()
    assert "código de salida 3" in d.lbl_estado.text() and "instalar" in d.lbl_estado.text()
    assert "boom" in d.salida.toPlainText()
    assert not d.btn_reiniciar.isVisibleTo(d)
    d.close()


def test_dialogo_actualizar_misma_version_no_pide_reiniciar(app, monkeypatch):
    import sys

    from spotyurl import actualizar
    from spotyurl.gui import DialogoActualizar

    monkeypatch.setattr(actualizar, "version_ytdlp", lambda: "2026.08.19")
    d = DialogoActualizar(comando=[sys.executable, "-c", "pass"],
                          comando_version=[sys.executable, "-c", "print('2026.08.19')"])
    _esperar(lambda: d.codigo is not None)
    assert d.ok and "ya está en la última versión" in d.lbl_estado.text()
    assert not d.btn_reiniciar.isVisibleTo(d)
    d.close()


def test_reiniciar_cierra_la_ventana_y_relanza(app, ajustes, monkeypatch):
    import sys

    from PySide6.QtCore import QProcess

    from spotyurl.gui import DialogoActualizar, MainWindow
    from spotyurl.paths import CARPETA_PROYECTO

    lanzados = []
    monkeypatch.setattr(QProcess, "startDetached", lambda *a: lanzados.append(a) or True)
    w = MainWindow(ajustes)
    w.show()
    d = DialogoActualizar(w, iniciar=False)
    d._reiniciar()
    assert not w.isVisible()
    assert lanzados == [(sys.executable, ["-m", "spotyurl.gui"], str(CARPETA_PROYECTO))]


def test_reiniciar_no_relanza_si_la_ventana_no_se_cierra(app, ajustes, monkeypatch):
    from PySide6.QtCore import QProcess

    from spotyurl.gui import DialogoActualizar, MainWindow

    lanzados = []
    monkeypatch.setattr(QProcess, "startDetached", lambda *a: lanzados.append(a) or True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    w = MainWindow(ajustes)
    w.show()
    w.worker = _WorkerFalso()
    DialogoActualizar(w, iniciar=False)._reiniciar()
    assert w.isVisible() and not lanzados
    w.worker = None
    w.close()


def test_no_se_actualiza_con_trabajo_en_curso(ventana, monkeypatch):
    from spotyurl.gui import DialogoAjustes, dialogo_actualizar

    avisos, abiertos = [], []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: avisos.append(a))
    monkeypatch.setattr(dialogo_actualizar.DialogoActualizar, "exec", lambda self: abiertos.append(self) or 0)
    ventana.worker = _WorkerFalso()
    ventana._actualizar_ytdlp()
    assert "Espera" in ventana.lbl_fase.texto_completo() and not abiertos
    # Desde Ajustes (hijo de la ventana) también se bloquea
    DialogoAjustes(ventana.ajustes, ventana).btn_actualizar.click()
    assert avisos and not abiertos
    ventana.worker = None


def test_dialogo_ajustes_muestra_version_y_abre_actualizar(app, ajustes, monkeypatch):
    from spotyurl import actualizar
    from spotyurl.gui import DialogoAjustes, dialogo_actualizar

    monkeypatch.setattr(actualizar, "version_ytdlp", lambda: "2026.08.19")
    abiertos = []
    monkeypatch.setattr(dialogo_actualizar.DialogoActualizar, "iniciar", lambda self: None)
    monkeypatch.setattr(dialogo_actualizar.DialogoActualizar, "exec", lambda self: abiertos.append(self) or 0)
    d = DialogoAjustes(ajustes)
    assert d.lbl_ytdlp.text().startswith("yt-dlp versión 2026.08.19 (hace ")
    d.btn_actualizar.click()
    assert len(abiertos) == 1


def test_texto_version():
    from datetime import date

    from spotyurl.gui.dialogo_actualizar import texto_version

    hoy = date(2026, 10, 22)
    assert texto_version("2026.08.19", hoy) == "yt-dlp versión 2026.08.19 (hace 64 días)"
    assert texto_version("2026.10.21", hoy) == "yt-dlp versión 2026.10.21 (de ayer)"
    assert texto_version("rara", hoy) == "yt-dlp versión rara"
    assert texto_version("", hoy) == "yt-dlp no está instalado"


def _fallo_total(ventana, tmp_path, motivo, monkeypatch, pulsar=None):
    from spotyurl.download import DownloadResult
    from spotyurl.gui import DEFAULTS, DownloadWorker

    cajas, actualizados = [], []

    def exec_falso(caja):
        cajas.append([b.text() for b in caja.buttons()])
        if pulsar:
            next(b for b in caja.buttons() if b.text() == pulsar).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_falso)
    monkeypatch.setattr(ventana, "_actualizar_ytdlp", lambda: actualizados.append(True))
    copias = [Track(title="a")]
    ventana.model.set_tracks([Track(title="a", youtube_url="https://youtu.be/a")])
    w = DownloadWorker(dict(DEFAULTS), copias, tmp_path)
    w.result = DownloadResult(failed=[(copias[0], motivo)])
    ventana._fin_descarga(w, False)
    assert len(cajas) == 1
    return cajas[0], actualizados


def test_aviso_fallo_ofrece_actualizar_solo_con_pista_de_ytdlp(ventana, monkeypatch, tmp_path):
    botones, actualizados = _fallo_total(ventana, tmp_path, "HTTP Error 403: Forbidden", monkeypatch)
    assert "Actualizar yt-dlp ahora" in botones and not actualizados
    botones, _ = _fallo_total(ventana, tmp_path, "algo raro sin consejo", monkeypatch)
    assert "Actualizar yt-dlp ahora" not in botones


def test_aviso_fallo_boton_abre_actualizar(ventana, monkeypatch, tmp_path):
    _, actualizados = _fallo_total(ventana, tmp_path, "Sign in to confirm you are not a bot", monkeypatch,
                                   pulsar="Actualizar yt-dlp ahora")
    assert actualizados == [True]


def test_franja_version_antigua(app, ajustes, monkeypatch):
    from datetime import date, timedelta

    from spotyurl import actualizar
    from spotyurl.gui import MainWindow

    reciente = (date.today() - timedelta(days=10)).strftime("%Y.%m.%d")
    monkeypatch.setattr(actualizar, "version_ytdlp", lambda: reciente)
    w = MainWindow(ajustes)
    assert not w.aviso_ytdlp.isVisibleTo(w)
    w.close()

    monkeypatch.setattr(actualizar, "version_ytdlp", lambda: "2020.01.01")
    w = MainWindow(ajustes)
    assert w.aviso_ytdlp.isVisibleTo(w)
    assert "2020.01.01" in w.lbl_aviso_ytdlp.text()
    w.btn_cerrar_aviso.click()
    assert not w.aviso_ytdlp.isVisibleTo(w)
    w.close()

    monkeypatch.setattr(actualizar, "version_ytdlp", lambda: "")   # sin yt-dlp: sin franja
    w = MainWindow(ajustes)
    assert not w.aviso_ytdlp.isVisibleTo(w)
    w.close()


def test_franja_limite_de_dias(ventana, monkeypatch):
    from datetime import date

    from spotyurl import actualizar

    monkeypatch.setattr(actualizar, "version_ytdlp", lambda: "2026.08.23")
    ventana.aviso_ytdlp.setVisible(False)
    ventana._comprobar_ytdlp(hoy=date(2026, 10, 22))    # 60 días: aún no
    assert not ventana.aviso_ytdlp.isVisibleTo(ventana)
    ventana._comprobar_ytdlp(hoy=date(2026, 10, 23))    # 61 días
    assert ventana.aviso_ytdlp.isVisibleTo(ventana)


# ── Sincronización, Recientes y abrir .csv ───────────────────────────────────

def _carpeta_descargada(carpeta, origen=ENLACE, formato="m4a", claves=("A",)):
    """Carpeta con manifiesto (vía guardar_manifiesto) y un archivo por canción."""
    from spotyurl.manifiesto import guardar_manifiesto, nuevo_manifiesto

    carpeta.mkdir(parents=True, exist_ok=True)
    m = nuevo_manifiesto(origen, "Mi lista", formato)
    for i, c in enumerate(claves, 1):
        archivo = f"{i:02d} - X - {c}.{formato}"
        (carpeta / archivo).write_bytes(b"x")
        m["canciones"][f"sp:{c}"] = {"archivo": archivo, "youtube_url": f"https://www.youtube.com/watch?v={c:_<11}",
                                     "youtube_titulo": f"X - {c}", "titulo": c, "artista": "X", "manual": False}
    guardar_manifiesto(carpeta, m)
    return carpeta


def test_resumen_descarga_con_renumeradas_y_quitadas(ventana, ajustes, tmp_path):
    from spotyurl.download import DownloadResult
    from spotyurl.gui import DEFAULTS, DownloadWorker

    copias = [Track(title="a", youtube_url="https://youtu.be/a"), Track(title="b", youtube_url="https://youtu.be/b")]
    ventana.model.set_tracks([dataclasses.replace(t) for t in copias])
    w = DownloadWorker(dict(DEFAULTS), copias, tmp_path, album="Mi lista", origen=ENLACE)
    w.result = DownloadResult(ok=[copias[0]], skipped=[copias[1]], renamed=[("02 - x.mp3", "01 - x.mp3")],
                              removed=["03 - y.mp3", "04 - z.mp3"])
    ventana._fin_descarga(w, False)
    assert ventana.lbl_fase.texto_completo() == \
        "Descargadas 1 · ya estaban 1 · renumeradas 1 · quitadas 2 · fallidas 0"
    assert ".m3u8" in ventana.btn_archivo.toolTip()
    r = ajustes.recientes()[0]   # la descarga queda en Recientes con su carpeta
    assert (r["url"], r["nombre"], r["carpeta"]) == (ENLACE, "Mi lista", str(tmp_path))


def test_actualizar_carpeta_sin_manifiesto_avisa(ventana, tmp_path, monkeypatch):
    avisos, lanzados = [], []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: avisos.append(a[2]))
    monkeypatch.setattr(ventana, "_lanzar", lambda w, guardar=True: lanzados.append(w))
    ventana._actualizar_descarga(tmp_path)                                   # sin manifiesto
    _carpeta_descargada(tmp_path / "sin_enlace", origen="")
    ventana._actualizar_descarga(tmp_path / "sin_enlace")                    # manifiesto sin enlace
    assert len(avisos) == 2 and not lanzados
    assert all("no se descargó con la app" in a and "Convertir" in a for a in avisos)


def test_actualizar_descarga_busca_solo_nuevas_y_descarga_en_la_carpeta(ventana, ajustes, tmp_path, monkeypatch):
    from spotyurl import youtube
    from spotyurl.download import DownloadResult
    from spotyurl.gui import DownloadWorker, Worker
    from spotyurl.gui import workers as mod_workers

    carpeta = _carpeta_descargada(tmp_path / "Mi lista", formato="m4a", claves=("A",))
    ajustes["out_dir"] = str(tmp_path / "enlaces")
    lanzados = []
    monkeypatch.setattr(ventana, "_lanzar", lambda w, guardar=True: lanzados.append((w, guardar)))
    monkeypatch.setattr(ventana, "_confirmar_actualizacion", lambda c, m: True)   # mover quitadas
    ventana._actualizar_descarga(carpeta)
    w, guardar = lanzados[0]
    assert isinstance(w, Worker) and guardar and w.url == ENLACE
    assert w.sync_folder == carpeta and w.mover_quitadas and w.manifiesto["formato"] == "m4a"
    assert ventana.modo == 0 and ventana.url.text() == ENLACE

    # El hilo (ejecutado aquí, sin red): extrae, aplica el manifiesto y busca solo la nueva
    def extraer(url, cfg, on_name=None, **kw):
        on_name("Mi lista")
        return [Track(title="A", artists=["X"], spotify_id="A"), Track(title="B", artists=["X"], spotify_id="B")]

    monkeypatch.setattr(mod_workers, "fetch_tracks", extraer)
    buscadas = []

    class Falso:
        def __init__(self, **kw):
            pass

        def match(self, t, cancel, use_cache=True):
            buscadas.append(t.title)
            t.youtube_url, t.status = "https://www.youtube.com/watch?v=BBBBBBBBBBB", Status.DOUBTFUL

        def save_cache(self):
            pass

    monkeypatch.setattr(youtube, "YouTubeMatcher", Falso)
    w.opts["clipboard"] = False
    w.tracks_reset.connect(ventana.model.set_tracks)
    w.track_updated.connect(ventana.model.update_track)
    w.name_found.connect(ventana._on_nombre)
    w.run()
    assert buscadas == ["B"] and w.reutilizadas == 1
    assert [t.status for t in ventana.model.tracks] == [Status.OK, Status.DOUBTFUL]

    # Al terminar, se guarda el .txt y se lanza la descarga en esa carpeta con su formato
    ventana._on_fin(w, True)
    d, guardar = lanzados[1]
    assert isinstance(d, DownloadWorker) and not guardar
    assert (d.folder, d.formato, d.album, d.origen, d.mover_quitadas) == (carpeta, "m4a", "Mi lista", ENLACE, True)
    assert [t.youtube_url for t in d.tracks] == ["https://www.youtube.com/watch?v=A__________",
                                                 "https://www.youtube.com/watch?v=BBBBBBBBBBB"]
    assert d.dudosas == 1
    assert (tmp_path / "enlaces" / "Mi lista.txt").exists()
    assert ajustes.recientes()[0]["carpeta"] == str(carpeta)

    # El resumen final recuerda las dudosas
    d.result = DownloadResult(ok=[d.tracks[1]], skipped=[d.tracks[0]])
    ventana._fin_descarga(d, False)
    assert ventana.lbl_fase.texto_completo().endswith("fallidas 0 · 1 dudosa para revisar")


def test_actualizar_descarga_cancelada_o_fallida_no_descarga(ventana, tmp_path, monkeypatch):
    from spotyurl.gui import DEFAULTS, Worker

    lanzados = []
    monkeypatch.setattr(ventana, "_lanzar", lambda w, guardar=True: lanzados.append(w))
    ventana.model.set_tracks([Track(title="A", youtube_url="https://youtu.be/a", status=Status.OK)])
    w = Worker(dict(DEFAULTS, auto_save=False), url=ENLACE, manifiesto={}, sync_folder=tmp_path)
    w.cancel.set()
    ventana._on_fin(w, True)
    w2 = Worker(dict(DEFAULTS, auto_save=False), url=ENLACE, manifiesto={}, sync_folder=tmp_path)
    w2.fallo = "Spotify no responde"
    ventana._on_fin(w2, True)
    assert lanzados == []


def test_actualizar_descarga_respeta_cancelar_confirmacion(ventana, tmp_path, monkeypatch):
    lanzados = []
    monkeypatch.setattr(ventana, "_lanzar", lambda w, guardar=True: lanzados.append(w))
    monkeypatch.setattr(ventana, "_confirmar_actualizacion", lambda c, m: None)
    ventana._actualizar_descarga(_carpeta_descargada(tmp_path / "L"))
    assert lanzados == []


def test_dialogo_descarga_casilla_quitadas(app, tmp_path):
    from spotyurl.gui.dialogo_descarga import DialogoDescarga

    _carpeta_descargada(tmp_path / "Mi lista", claves=("A", "Z"))
    tracks = [Track(title="A", spotify_id="A", youtube_url="u"), Track(title="B", spotify_id="B", youtube_url="u")]
    d = DialogoDescarga(2, tmp_path, "Mi lista", "mp3", True, tracks=tracks)
    assert d.quitadas.isVisibleTo(d) and "la canción que ya no está" in d.quitadas.text()
    assert d.lbl_existe.isVisibleTo(d)
    assert not d.mover_quitadas()
    d.quitadas.setChecked(True)
    assert d.mover_quitadas()
    d.nombre.setText("Otra lista")                    # carpeta nueva: sin casilla
    assert not d.quitadas.isVisibleTo(d) and not d.mover_quitadas()


def test_recientes_agregar_deduplicar_maximo_borrar(ajustes):
    from spotyurl.gui.ajustes import MAX_RECIENTES

    assert ajustes.recientes() == []
    ajustes.agregar_reciente(ENLACE, "Uno", fecha="2026-10-01T10:00")
    ajustes.agregar_reciente(ENLACE + "x", "Dos", "C:/musica/Dos")
    ajustes.agregar_reciente(ENLACE, "Uno bis", "C:/musica/Uno")
    assert [r["nombre"] for r in ajustes.recientes()] == ["Uno bis", "Dos"]   # sin duplicados, la última primero
    ajustes.agregar_reciente(ENLACE, "Uno bis")                               # conversión: conserva la carpeta
    assert ajustes.recientes()[0]["carpeta"] == "C:/musica/Uno"
    ajustes.agregar_reciente("https://open.spotify.com/album/otro", "Otro", "C:/musica/Dos")   # misma carpeta
    assert [r["nombre"] for r in ajustes.recientes()] == ["Otro", "Uno bis"]
    for i in range(15):
        ajustes.agregar_reciente(f"{ENLACE}{i}", f"L{i}")
    assert len(ajustes.recientes()) == MAX_RECIENTES and ajustes.recientes()[0]["nombre"] == "L14"
    ajustes.borrar_recientes()
    assert ajustes.recientes() == []
    ajustes._s.setValue("recientes", "{roto")
    assert ajustes.recientes() == []


def test_menu_recientes_se_construye(ventana, ajustes, tmp_path, monkeypatch):
    from spotyurl.gui.ventana import texto_reciente

    ventana._construir_menu_recientes()
    assert "(sin listas recientes)" in [a.text() for a in ventana.menu_recientes.actions()]
    ajustes.agregar_reciente(ENLACE, "Sin carpeta", fecha="2026-10-22T09:30")
    ajustes.agregar_reciente("https://open.spotify.com/album/abc", "Descargada", tmp_path, fecha="2026-10-21T08:00")
    ventana._construir_menu_recientes()
    acciones = ventana.menu_recientes.actions()
    assert acciones[0].text() == "Descargada — 21/10/2026" and acciones[0].menu() is not None
    assert [a.text() for a in acciones[0].menu().actions()] == ["Convertir de nuevo", "⟳  Actualizar descarga",
                                                                "Abrir carpeta"]
    assert acciones[1].text() == texto_reciente(ajustes.recientes()[1]) == "Sin carpeta — 22/10/2026"
    assert [a.text() for a in acciones[-2:]] == ["⟳  Actualizar una descarga…", "Borrar recientes"]

    convertidos, actualizadas = [], []
    monkeypatch.setattr(ventana, "_convertir", lambda: convertidos.append(ventana.url.text()))
    monkeypatch.setattr(ventana, "_actualizar_descarga", lambda c=None: actualizadas.append(c))
    ventana._cambiar_modo(1)
    acciones[1].trigger()
    assert ventana.modo == 0 and convertidos == [ENLACE]
    ventana._construir_menu_recientes()
    ventana.menu_recientes.actions()[0].menu().actions()[1].trigger()
    assert actualizadas == [tmp_path]
    ventana.menu_recientes.actions()[-1].trigger()   # Borrar recientes
    assert ajustes.recientes() == []

    ventana.worker = _WorkerFalso()                  # ocupado: deshabilitado
    ventana._set_ocupado(True)
    assert not ventana.btn_recientes.isEnabled()
    ventana.worker = None
    ventana._set_ocupado(False)
    assert ventana.btn_recientes.isEnabled()


def test_abrir_csv_propio_carga_la_tabla(ventana, tmp_path, monkeypatch):
    from spotyurl.export import to_csv

    lanzados = []
    monkeypatch.setattr(ventana, "_lanzar", lambda w, guardar=True: lanzados.append(w))
    ruta = tmp_path / "Mi lista.csv"
    to_csv([Track(title="A", artists=["X"], youtube_url="https://www.youtube.com/watch?v=aaaaaaaaaaa",
                  status=Status.OK),
            Track(title="B", artists=["Y"], status=Status.FAILED)], ruta)
    ventana.texto.setPlainText("algo")
    ventana._abrir_csv(ruta)
    m = ventana.model
    assert [(t.title, t.status) for t in m.tracks] == [("A", Status.OK), ("B", Status.FAILED)]
    assert ventana.nombre_lista == "Mi lista" and ventana.origen_lista == ""
    assert ventana.modo == 1 and ventana.texto.toPlainText() == ""
    assert not lanzados                                  # ya traen enlaces: no se busca solo
    assert "1 sin enlace" in ventana.lbl_fase.texto_completo()
    assert ventana.btn_reintentar.isEnabled()


def test_abrir_csv_exportify_busca_todas(ventana, tmp_path, monkeypatch):
    lanzados = []
    monkeypatch.setattr(ventana, "_lanzar", lambda w, guardar=True: lanzados.append((w, guardar)))
    ruta = tmp_path / "Exportify.csv"
    ruta.write_text("Track URI,Track Name,Artist Name(s),Album Name,Duration (ms)\n"
                    "spotify:track:4uLU6hMCjMI75M1A2tKUQC,Never Gonna,Rick Astley,Whenever,213000\n"
                    'spotify:track:1111111111111111111111,Otra,"A, B",Disco,180000\n', encoding="utf-8")
    ventana._abrir_csv(ruta)
    assert [t.title for t in ventana.model.tracks] == ["Never Gonna", "Otra"]
    assert ventana.model.tracks[1].artists == ["A", "B"]
    w, guardar = lanzados[0]
    assert [r for r, _ in w.items] == [0, 1] and guardar     # como una conversión (auto-guardado)
    assert ventana.nombre_lista == "Exportify"


def test_soltar_csv_lo_abre(ventana, tmp_path, monkeypatch):
    from spotyurl.gui.ventana import contenido_drop

    ruta = tmp_path / "lista.CSV"
    ruta.write_text("x", encoding="utf-8")
    abiertos = []
    monkeypatch.setattr(ventana, "_abrir_csv", lambda r=None: abiertos.append(r))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(ruta))])
    assert contenido_drop(mime)[0] == "csv"
    _soltar(ventana, mime)
    assert [p.name for p in abiertos] == ["lista.CSV"]


def test_abrir_csv_erroneo_avisa(ventana, tmp_path, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    ruta = tmp_path / "raro.csv"
    ruta.write_text("foo,bar\n1,2\n", encoding="utf-8")
    ventana.model.set_tracks([Track(title="sigue")])
    ventana._abrir_csv(ruta)
    ventana._abrir_csv(tmp_path / "no_existe.csv")
    assert len(avisos) == 2 and "No se reconocen las columnas" in avisos[0]
    assert [t.title for t in ventana.model.tracks] == ["sigue"]   # la tabla no se toca
