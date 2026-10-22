"""Modelo de la tabla de canciones y su filtro."""

from bisect import bisect_left

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor

from ..download import (
    ESTADO_COLA, ESTADO_CONVIRTIENDO, ESTADO_DESCARGANDO, ESTADO_ERROR, ESTADO_ETIQUETANDO, ESTADO_EXISTE,
    ESTADO_OK, ESTADOS_AUDIO,
)
from ..models import Status, Track, fmt_duration
from .constantes import ETIQUETA_ESTADO, RE_YOUTUBE
from .tema import colores_estado


# ── Modelo de la tabla ───────────────────────────────────────────────────────

ROL_ORDEN = Qt.UserRole        # valor con el que se ordena cada columna (números donde toca)
ROL_ESTADO = Qt.UserRole + 1

# Orden de los estados al ordenar por la columna Estado (lo que hay que revisar, primero)
ORDEN_ESTADO = {s: i for i, s in enumerate(
    (Status.DOUBTFUL, Status.FAILED, Status.MANUAL, Status.OK, Status.SEARCHING, Status.PENDING))}


def texto_audio(estado: str, pct: float) -> str:
    """Texto de la columna Audio para un estado de download.ESTADOS_AUDIO."""
    if estado == ESTADO_DESCARGANDO:
        return f"⬇ {pct:.0f} %"
    return {
        ESTADO_COLA: "en cola", ESTADO_CONVIRTIENDO: "convirtiendo…", ESTADO_ETIQUETANDO: "etiquetando…",
        ESTADO_OK: "✓", ESTADO_EXISTE: "ya existía", ESTADO_ERROR: "✗",
    }.get(estado, "")


class TrackTableModel(QAbstractTableModel):
    COLUMNAS = ["#", "Título", "Artista", "Duración", "Estado", "Audio", "Vídeo encontrado", "Enlace de YouTube"]
    COL_NUM, COL_TITULO, COL_ARTISTA, COL_DURACION, COL_ESTADO, COL_AUDIO, COL_VIDEO, COL_ENLACE = range(8)
    enlace_rechazado = Signal(str)   # se pegó algo que no es un enlace de YouTube
    enlace_editado = Signal(int)     # se pegó o se borró a mano el enlace de una fila

    def __init__(self, tema: str = "dark"):
        super().__init__()
        self.tracks: list[Track] = []
        # Descarga de audio por fila (fila = índice en la lista que recibe download_tracks)
        self.audio: dict[int, tuple[str, float]] = {}
        self.motivos_audio: dict[int, str] = {}   # fila -> motivo del fallo de descarga
        self.colores = colores_estado(tema)
        self.editable = True   # False mientras hay trabajo en curso (el hilo sobrescribiría la edición)

    def set_tema(self, tema: str):
        self.colores = colores_estado(tema)
        if self.tracks:
            self.dataChanged.emit(self.index(0, self.COL_ESTADO), self.index(len(self.tracks) - 1, self.COL_AUDIO),
                                  [Qt.ForegroundRole])

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.tracks)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNAS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNAS[section]
        return None

    def _orden(self, row: int, t: Track, col: int):
        if col == self.COL_NUM:
            return row
        if col == self.COL_DURACION:
            return t.duration_s if t.duration_s is not None else -1
        if col == self.COL_ESTADO:
            return ORDEN_ESTADO[t.status]
        if col == self.COL_AUDIO:
            estado = self.audio.get(row)
            return ESTADOS_AUDIO.index(estado[0]) if estado else -1
        return [None, t.title, t.artist, None, None, None, t.youtube_title, t.youtube_url][col].lower()

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        t = self.tracks[row]
        if role in (Qt.DisplayRole, Qt.EditRole):
            audio = self.audio.get(row)
            return [
                row + 1, t.title, t.artist, fmt_duration(t.duration_s),
                f"●  {ETIQUETA_ESTADO[t.status]}", texto_audio(*audio) if audio else "",
                t.youtube_title, t.youtube_url,
            ][col]
        if role == ROL_ORDEN:
            return self._orden(row, t, col)
        if role == Qt.ForegroundRole and col == self.COL_ESTADO:
            return QColor(self.colores[t.status])
        if role == Qt.ForegroundRole and col == self.COL_AUDIO and row in self.audio:
            estado = self.audio[row][0]
            clave = {ESTADO_OK: Status.OK, ESTADO_EXISTE: Status.OK, ESTADO_ERROR: Status.FAILED,
                     ESTADO_COLA: Status.PENDING}.get(estado, Status.SEARCHING)
            return QColor(self.colores[clave])
        if role == Qt.ToolTipRole:
            if col == self.COL_AUDIO:
                if self.audio.get(row, ("",))[0] == ESTADO_ERROR:
                    return f"No se pudo descargar: {self.motivos_audio.get(row) or 'error desconocido'}"
                return None
            if col in (self.COL_ENLACE, self.COL_VIDEO) and t.youtube_title:
                score = "" if t.score is None else f"  ·  puntuación {t.score:.2f}"
                accion = "Doble clic para pegar otro enlace" if col == self.COL_ENLACE else \
                    "Clic derecho → «Elegir otra versión…» para cambiarlo"
                return f"{t.youtube_title}{score}\n{accion}"
            if col == self.COL_ENLACE:
                return "Doble clic para pegar un enlace de YouTube"
            if not t.youtube_url:
                return "Doble clic para buscarla a mano en YouTube"
            if col == self.COL_TITULO and t.album:
                return f"Álbum: {t.album}"
        if role == Qt.TextAlignmentRole and col in (self.COL_NUM, self.COL_DURACION):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == ROL_ESTADO:
            return t.status
        return None

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemIsEditable if index.column() == self.COL_ENLACE and self.editable else f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or index.column() != self.COL_ENLACE or not self.editable:
            return False
        t = self.tracks[index.row()]
        value = str(value).strip()
        if not value:
            t.youtube_url, t.youtube_title, t.score, t.status = "", "", None, Status.FAILED
        else:
            m = RE_YOUTUBE.search(value)
            if not m:
                self.enlace_rechazado.emit(value)
                return False
            url = f"https://www.youtube.com/watch?v={m.group(1)}"
            # Si es uno de los candidatos ya conocidos, se conserva su título y puntuación
            cand = next((c for c in t.candidates if c.url == url), None)
            t.youtube_url = url
            t.youtube_title, t.score = (cand.title, cand.score) if cand else ("", None)
            t.status = Status.MANUAL
        self._row_changed(index.row())
        self.enlace_editado.emit(index.row())
        return True

    # API usada por la ventana
    def _row_changed(self, row):
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))

    def set_tracks(self, tracks: list[Track]):
        self.beginResetModel()
        self.tracks = list(tracks)
        self.audio.clear()
        self.motivos_audio.clear()
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

    def usar_candidato(self, row: int, cand, candidatos: list | None = None):
        """Elige a mano el vídeo `cand` (youtube.Candidate) para la fila: pasa a MANUAL."""
        t = self.tracks[row]
        t.youtube_url, t.youtube_title, t.score, t.status = cand.url, cand.title, cand.score, Status.MANUAL
        if candidatos:
            t.candidates = list(candidatos)
        self._row_changed(row)

    def marcar_correcta(self, row: int) -> bool:
        """Da por buena una fila dudosa (o sin enlace con enlace): pasa a MANUAL."""
        t = self.tracks[row]
        if not t.youtube_url or t.status not in (Status.DOUBTFUL, Status.FAILED):
            return False
        t.status = Status.MANUAL
        self._row_changed(row)
        return True

    def remove_rows(self, rows: list[int]):
        quitadas = sorted(set(rows))
        for row in reversed(quitadas):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.tracks[row]
            self.endRemoveRows()
        if quitadas and (self.audio or self.motivos_audio):
            # Las filas siguientes suben: se reindexa el estado de la descarga
            def reindexar(d: dict) -> dict:
                return {i - bisect_left(quitadas, i): v for i, v in d.items() if i not in quitadas}
            self.audio, self.motivos_audio = reindexar(self.audio), reindexar(self.motivos_audio)
            self._audio_changed()

    # Estado de la descarga de audio
    def _audio_changed(self, row: int | None = None):
        if row is not None:
            i = self.index(row, self.COL_AUDIO)
            self.dataChanged.emit(i, i)
        elif self.tracks:
            self.dataChanged.emit(self.index(0, self.COL_AUDIO), self.index(len(self.tracks) - 1, self.COL_AUDIO))

    def set_audio(self, row: int, estado: str, pct: float = 0.0):
        if 0 <= row < len(self.tracks):
            self.audio[row] = (estado, pct)
            if estado != ESTADO_ERROR:
                self.motivos_audio.pop(row, None)
            self._audio_changed(row)

    def set_motivo_audio(self, row: int, motivo: str):
        if 0 <= row < len(self.tracks):
            self.motivos_audio[row] = motivo
            self._audio_changed(row)

    def limpiar_audio(self):
        if self.audio or self.motivos_audio:
            self.audio.clear()
            self.motivos_audio.clear()
            self._audio_changed()

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
        self.setSortRole(ROL_ORDEN)   # # y Duración se ordenan como números

    def set_filtro(self, texto: str, estados: set[Status] | None):
        self.texto, self.estados = texto.lower().strip(), estados
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        t = self.sourceModel().tracks[row]
        if self.estados is not None and t.status not in self.estados:
            return False
        return not self.texto or self.texto in f"{t.title} {t.artist} {t.album}".lower()

    def lessThan(self, izq, der):
        a, b = izq.data(ROL_ORDEN), der.data(ROL_ORDEN)
        if a == b:
            # Desempate estable por posición en la lista
            return izq.row() < der.row()
        return a < b
