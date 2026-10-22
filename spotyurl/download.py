"""
Descarga del audio de las canciones con yt-dlp.

Cada canción con enlace de YouTube se guarda como "NN - Artista - Título" en la
carpeta indicada, en .mp3 o .m4a. ffmpeg viene incluido con imageio-ffmpeg
(se usa el del sistema si existe); sin ninguno se guarda en el formato original
(.m4a/.webm). Las que ya existen en la carpeta se saltan.
"""


import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .models import Track
from .paths import safe_filename

EXTENSIONES_AUDIO = {".mp3", ".m4a", ".webm", ".opus", ".ogg", ".aac", ".flac", ".wav"}
ESPERAS_REINTENTO = (0, 5, 15, 45)

FORMATOS_AUDIO = {
    "mp3": "MP3 (compatible con todo)",
    "m4a": "M4A / AAC (sin recomprimir, algo mejor calidad)",
}


class DescargaCancelada(Exception):
    """Lanzada desde el progress_hook cuando el usuario cancela."""


@dataclass
class DownloadResult:
    ok: list[Track] = field(default_factory=list)
    skipped: list[Track] = field(default_factory=list)      # ya estaban descargadas
    failed: list[tuple[Track, str]] = field(default_factory=list)   # (track, motivo)


def ffmpeg_path() -> str | None:
    """ffmpeg del sistema o, si no hay, el que trae el paquete imageio-ffmpeg."""
    sistema = shutil.which("ffmpeg")
    if sistema:
        return sistema
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def ffmpeg_disponible() -> bool:
    return ffmpeg_path() is not None


def nombre_archivo(posicion: int, total: int, track: Track) -> str:
    """
    Nombre (sin extensión) para la canción en la posición 1-based `posicion`
    de una lista de `total` canciones: (3, 120, t) -> '003 - Artista - Título'.
    """
    ancho = max(2, len(str(total)))
    return safe_filename(f"{posicion:0{ancho}d} - {track.label}")


def _existentes(folder: Path) -> dict[str, set[str]]:
    """stem -> extensiones de audio ya presentes (sin glob: los títulos pueden llevar [ ])."""
    vistos: dict[str, set[str]] = {}
    try:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in EXTENSIONES_AUDIO:
                vistos.setdefault(p.stem, set()).add(p.suffix.lower())
    except OSError:
        pass
    return vistos


def _mensaje_corto(error: Exception) -> str:
    texto = (str(error).strip().splitlines() or [""])[0].strip()
    if texto.startswith("ERROR: "):
        texto = texto[len("ERROR: "):]
    return texto or type(error).__name__


def pista_error(motivo: str) -> str:
    """Consejo para el usuario según el error de yt-dlp ("" si no hay ninguno)."""
    if re.search(r"403|forbidden|sign in|not a bot|unavailable|nsig|signature", motivo, re.I):
        return ("YouTube rechazó la descarga. Suele arreglarse actualizando yt-dlp: "
                "vuelve a ejecutar instalar (o: python -m pip install -U \"yt-dlp[default]\").")
    if re.search(r"ffmpeg|ffprobe", motivo, re.I):
        return ("ffmpeg no funciona: vuelve a ejecutar instalar o instala ffmpeg "
                "(winget install ffmpeg / brew install ffmpeg).")
    return ""


def _opciones(folder: Path, stem: str, ffmpeg: str | None, formato: str,
              hook: Callable[[dict], None]) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(folder / stem).replace("%", "%%") + ".%(ext)s",
        "progress_hooks": [hook],
    }
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
        # Con m4a el audio AAC de YouTube se copia sin recomprimir
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": formato,
            "preferredquality": "192",
        }]
    return opts


def _descargar_una(url: str, opts: dict, cancel: threading.Event | None) -> None:
    from yt_dlp import YoutubeDL

    for intento, espera in enumerate(ESPERAS_REINTENTO):
        if espera:
            if cancel and cancel.wait(espera):
                raise DescargaCancelada()
            if not cancel:
                time.sleep(espera)
        try:
            # Una instancia nueva por canción: cada una tiene su propio outtmpl
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
            return
        except DescargaCancelada:
            raise
        except Exception as e:
            # 429 / "confirm you're not a bot": reintentar con espera creciente
            if intento == len(ESPERAS_REINTENTO) - 1 or not re.search(r"429|too many|not a bot", str(e), re.I):
                raise


def download_tracks(
    tracks: list[Track],
    folder: Path,
    on_progress: Callable[[int, int], None] | None = None,   # (hechas, total)
    on_log: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
    formato: str = "mp3",   # clave de FORMATOS_AUDIO
) -> DownloadResult:
    """Descarga el audio de las canciones con enlace. No relanza al cancelar."""
    if formato not in FORMATOS_AUDIO:
        raise ValueError(f"Formato de audio no soportado: {formato}")
    log = on_log or (lambda _msg: None)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = DownloadResult()

    # La posición se calcula sobre la lista completa para que sea estable
    pendientes = [(i, t) for i, t in enumerate(tracks, 1) if t.youtube_url]
    total = len(pendientes)
    if not total:
        return result

    ffmpeg = ffmpeg_path() if ffmpeg_disponible() else None
    if not ffmpeg:
        log("ffmpeg no encontrado: el audio se guardará en su formato original (.m4a/.webm). "
            "Vuelve a ejecutar instalar para obtener .mp3.")

    existentes = _existentes(folder)

    def hook(_d: dict) -> None:
        if cancel and cancel.is_set():
            raise DescargaCancelada()

    for hechas, (pos, track) in enumerate(pendientes, 1):
        if cancel and cancel.is_set():
            log("Descarga cancelada.")
            break
        stem = nombre_archivo(pos, len(tracks), track)
        ya = existentes.get(stem, set())
        # Con ffmpeg solo cuenta el formato elegido (cambiar de formato vuelve a descargar)
        if (f".{formato}" in ya) if ffmpeg else ya:
            result.skipped.append(track)
            log(f"[{hechas}/{total}] Ya existe: {stem}")
        else:
            try:
                _descargar_una(track.youtube_url, _opciones(folder, stem, ffmpeg, formato, hook), cancel)
            except Exception as e:
                if isinstance(e, DescargaCancelada) or (cancel and cancel.is_set()):
                    log("Descarga cancelada.")
                    break
                motivo = _mensaje_corto(e)
                result.failed.append((track, motivo))
                log(f"[{hechas}/{total}] Error: {track.label} — {motivo}")
            else:
                result.ok.append(track)
                existentes.setdefault(stem, set()).add(f".{formato}")
                log(f"[{hechas}/{total}] Descargada: {stem}")
        if on_progress:
            on_progress(hechas, total)
    return result
