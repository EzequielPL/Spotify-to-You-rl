"""
Hilos de trabajo. Todo el trabajo pesado (Playwright + yt-dlp) corre en un
QThread que habla con la UI mediante señales; la UI nunca toca Playwright.
"""

import dataclasses
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..models import Status, Track
from ..spotify import ScrapeConfig, SpotifyError, fetch_tracks
from .constantes import CACHE_PATH


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
    name_found = Signal(str)   # nombre de la playlist/álbum

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
            on_name=self.name_found.emit,
        )
        self.tracks_reset.emit([dataclasses.replace(t) for t in tracks])
        self.items = list(enumerate(tracks))
        self.log.emit(f"{len(tracks)} canciones extraídas.")

    def _buscar(self):
        from ..youtube import YouTubeMatcher

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


class DownloadWorker(Worker):
    """Descarga el audio de las canciones con enlace. Reutiliza las señales y el
    `cancel` de Worker, pero no extrae ni busca nada."""

    def __init__(self, opts: dict, tracks: list[Track], folder: Path):
        super().__init__(opts)
        self.tracks, self.folder = tracks, folder
        self.result = None   # DownloadResult al terminar (None si hubo error)

    def run(self):
        from ..download import download_tracks

        try:
            # La barra cuenta solo las canciones con enlace (las que se descargan)
            self.phase.emit("Descargando audio…", sum(bool(t.youtube_url) for t in self.tracks))
            self.result = download_tracks(
                self.tracks, self.folder,
                on_progress=lambda k, _n: self.progress.emit(k),
                on_log=self.log.emit,
                cancel=self.cancel,
            )
        except Exception as e:
            self.log.emit(traceback.format_exc())
            self.failed.emit(f"Error al descargar: {e}")
