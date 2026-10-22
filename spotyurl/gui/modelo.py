"""Modelo de la tabla de canciones y su filtro."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from ..models import Status, Track, fmt_duration
from .constantes import COLOR_ESTADO, RE_YOUTUBE


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
