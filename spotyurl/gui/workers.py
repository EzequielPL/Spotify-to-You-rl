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
                 items: list[tuple[int, Track]] | None = None, use_cache: bool = True,
                 manifiesto: dict | None = None, sync_folder: Path | None = None,
                 mover_quitadas: bool = False):
        super().__init__()
        self.opts, self.url, self.items, self.use_cache = opts, url, items or [], use_cache
        self.cancel = threading.Event()
        self.errores = 0   # errores registrados en el log (el botón Log muestra cuántos)
        self.fallo = ""    # mensaje de la señal failed (la operación no se completó)
        # «Actualizar descarga»: las canciones del manifiesto reutilizan su enlace
        # y, al terminar, la ventana descarga en sync_folder (ver MainWindow._on_fin)
        self.manifiesto, self.sync_folder, self.mover_quitadas = manifiesto, sync_folder, mover_quitadas
        self.reutilizadas = 0   # canciones a las que se aplicó el manifiesto

    def run(self):
        try:
            if self.url:
                self._extraer()
            if not self.cancel.is_set():
                self._buscar()
        except SpotifyError as e:
            self._fallar(str(e))
        except Exception as e:
            self.log.emit(traceback.format_exc())
            self._fallar(f"Error inesperado: {e}")

    def _fallar(self, msg: str):
        self.errores += 1
        self.fallo = msg
        self.failed.emit(msg)

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
        self.log.emit(f"{len(tracks)} canciones extraídas.")
        if self.manifiesto:
            from ..manifiesto import aplicar_manifiesto

            self.reutilizadas = aplicar_manifiesto(tracks, self.manifiesto)
            if self.reutilizadas:
                self.log.emit(f"{self.reutilizadas} canciones ya descargadas reutilizan su enlace "
                              "(no se buscan de nuevo).")
        self.tracks_reset.emit([dataclasses.replace(t) for t in tracks])
        # Solo se buscan las que no tienen enlace (las del manifiesto ya lo traen)
        self.items = [(i, t) for i, t in enumerate(tracks) if not t.youtube_url]

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
                    self.errores += 1
                    self.log.emit(f"Error YouTube en «{t.label}»: {e}")
                if self.cancel.is_set() and t.status == Status.SEARCHING:
                    t.status = Status.PENDING
                self.track_updated.emit(row, dataclasses.replace(t))
                self.progress.emit(k)
                # Solo las seguras: una dudosa en el gestor de descargas suele ser otra canción
                if t.youtube_url and t.status in (Status.OK, Status.MANUAL) and self.opts["clipboard"]:
                    self.copy_request.emit(t.youtube_url)
                    if k < len(self.items):
                        self.cancel.wait(self.opts["pause"])
        finally:
            matcher.save_cache()


class DownloadWorker(Worker):
    """Descarga el audio de las canciones con enlace. Reutiliza las señales y el
    `cancel` de Worker, pero no extrae ni busca nada."""

    audio_estado = Signal(int, str, float)   # (índice en tracks, estado de download.ESTADOS_AUDIO, %)

    def __init__(self, opts: dict, tracks: list[Track], folder: Path, album: str = "",
                 origen: str = "", mover_quitadas: bool = False, formato: str | None = None):
        super().__init__(opts, mover_quitadas=mover_quitadas)
        self.tracks, self.folder, self.album, self.origen = tracks, folder, album, origen
        self.formato = formato or opts["audio_format"]   # «Actualizar descarga» usa el de la carpeta
        self.result = None   # DownloadResult al terminar (None si hubo error)
        self.dudosas = 0     # dudosas de la lista (se recuerdan en el resumen de «Actualizar descarga»)

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
                formato=self.formato,
                album=self.album,
                on_track=self.audio_estado.emit,
                origen=self.origen,
                mover_quitadas=self.mover_quitadas,
            )
        except Exception as e:
            self.log.emit(traceback.format_exc())
            self._fallar(f"Error al descargar: {e}")
        else:
            self.errores += len(self.result.failed)


class CandidatosWorker(QThread):
    """Busca en YouTube los candidatos de una canción (diálogo «Elegir otra versión»)."""

    listos = Signal(list)    # list[youtube.Candidate], de mejor a peor
    failed = Signal(str)

    def __init__(self, opts: dict, track: Track):
        super().__init__()
        self.opts, self.track = opts, dataclasses.replace(track)
        self.cancel = threading.Event()

    def run(self):
        from ..youtube import YouTubeMatcher

        try:
            matcher = YouTubeMatcher(n_results=self.opts["n_results"], query_template=self.opts["query_template"])
            cands = matcher.candidates(self.track, self.cancel)
        except Exception as e:
            if not self.cancel.is_set():
                self.failed.emit(str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__)
            return
        if not self.cancel.is_set():
            self.listos.emit(cands)
