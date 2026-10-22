"""
Descarga del audio de las canciones con yt-dlp.

Cada canción con enlace de YouTube se guarda como "NN - Artista - Título" en la
carpeta indicada, en .mp3 o .m4a. ffmpeg viene incluido con imageio-ffmpeg
(se usa el del sistema si existe); sin ninguno se guarda en el formato original
(.m4a/.webm).

Sincronización: cada carpeta lleva un manifiesto oculto (.spotyurl.json, ver
manifiesto.py) que asocia cada canción (id de Spotify) con su archivo. Al
volver a descargar la misma lista solo se descargan las nuevas; las que han
cambiado de posición se renombran a su número nuevo; las que ya no están se
informan (y opcionalmente se mueven a «Quitadas/»). Las carpetas antiguas sin
manifiesto se adoptan por nombre. Al final se escribe <lista>.m3u8 con los
archivos de la carpeta en el orden de la playlist.

Tras descargar, los .mp3 (ID3) y .m4a (MP4) se etiquetan con mutagen: título,
artista(s), álbum, artista del álbum, número de pista y carátula.
- Álbum: el de Spotify (track.album) o, si no hay, el parámetro `album`
  (nombre de la playlist).
- Artista del álbum: el primer artista si el álbum es el de Spotify;
  "Varios artistas" si es el nombre de la playlist (así los reproductores
  agrupan la playlist como un único álbum).
- Número de pista: posición en la lista completa / total (igual que el nombre).
- Carátula: la de Spotify (oEmbed) o, si falla, la miniatura de YouTube
  recortada a cuadrado. Un fallo al etiquetar nunca hace fallar la canción.
"""


import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .export import unique_path
from .manifiesto import (   # noqa: F401 (la GUI y la CLI los importan desde aquí)
    ARCHIVO_MANIFIESTO, aplicar_manifiesto, clave_track, claves_unicas, guardar_manifiesto,
    leer_manifiesto, nuevo_manifiesto,
)
from .models import Status, Track
from .paths import safe_filename

EXTENSIONES_AUDIO = {".mp3", ".m4a", ".webm", ".opus", ".ogg", ".aac", ".flac", ".wav"}
CARPETA_QUITADAS = "Quitadas"   # subcarpeta para las canciones que ya no están en la lista
ESPERAS_REINTENTO = (0, 5, 15, 45)
ARTISTA_VARIOS = "Varios artistas"
TIMEOUT_RED = 10
INTERVALO_PROGRESO = 0.25   # s entre avisos de porcentaje por canción (~4/s)

# Estados que recibe on_track(indice, estado, pct)
ESTADO_COLA = "cola"
ESTADO_DESCARGANDO = "descargando"
ESTADO_CONVIRTIENDO = "convirtiendo"
ESTADO_ETIQUETANDO = "etiquetando"
ESTADO_OK = "ok"
ESTADO_EXISTE = "existe"
ESTADO_ERROR = "error"
ESTADOS_AUDIO = (ESTADO_COLA, ESTADO_DESCARGANDO, ESTADO_CONVIRTIENDO, ESTADO_ETIQUETANDO,
                 ESTADO_OK, ESTADO_EXISTE, ESTADO_ERROR)

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
    renamed: list[tuple[str, str]] = field(default_factory=list)    # (archivo antes, después)
    removed: list[str] = field(default_factory=list)   # archivos de canciones que ya no están en la lista


@lru_cache(maxsize=1)
def ffmpeg_path() -> str | None:
    """ffmpeg del sistema o, si no hay, el que trae el paquete imageio-ffmpeg (se busca una vez)."""
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


def _descargar_una(url: str, opts: dict, cancel: threading.Event | None) -> dict | None:
    """Descarga (y convierte) una canción. Devuelve el info dict de yt-dlp."""
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
                return ydl.extract_info(url, download=True)
        except DescargaCancelada:
            raise
        except Exception as e:
            # 429 / "confirm you're not a bot": reintentar con espera creciente
            if intento == len(ESPERAS_REINTENTO) - 1 or not re.search(r"429|too many|not a bot", str(e), re.I):
                raise
    return None


def _archivo_final(info: dict | None, folder: Path, stem: str, formato: str) -> Path | None:
    """Archivo de audio producido (tras la conversión, si la hubo)."""
    info = info or {}
    for d in info.get("requested_downloads") or [info]:
        ruta = d.get("filepath") if isinstance(d, dict) else None
        if ruta and Path(ruta).is_file():
            return Path(ruta)
    # Respaldo: buscar "stem.*" en la carpeta
    ext = _existentes(folder).get(stem, set())
    if not ext:
        return None
    mejor = f".{formato}" if f".{formato}" in ext else sorted(ext)[0]
    return folder / f"{stem}{mejor}"


# ── Carátulas ───────────────────────────────────────────────────────────────

def _leer_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_RED) as r:
        return r.read()


def _tipo_imagen(datos: bytes | None) -> str | None:
    if not datos:
        return None
    if datos[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


def _recortar_cuadrado(datos: bytes, ffmpeg: str) -> bytes | None:
    """Recorta al centro una imagen (jpg/webp/png) a cuadrado y la devuelve en jpg."""
    with tempfile.TemporaryDirectory() as tmp:
        entrada, salida = Path(tmp) / "entrada", Path(tmp) / "salida.jpg"
        entrada.write_bytes(datos)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # sin consola en Windows
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(entrada),
             "-vf", "crop='min(iw,ih)':'min(iw,ih)'", "-frames:v", "1", "-q:v", "2", str(salida)],
            check=True, capture_output=True, timeout=30, creationflags=flags,
        )
        return salida.read_bytes() if salida.is_file() else None


class _Portadas:
    """Obtiene carátulas y las cachea por URL durante una llamada a download_tracks."""

    def __init__(self, ffmpeg: str | None, log: Callable[[str], None]):
        self.ffmpeg = ffmpeg
        self.log = log
        self._cache: dict[str, bytes | None] = {}

    def _imagen(self, url: str, cuadrar: bool) -> bytes | None:
        clave = f"cuadrada:{url}" if cuadrar else url
        if clave not in self._cache:
            datos = None
            try:
                datos = _leer_url(url)
                if cuadrar:
                    # Sin ffmpeg se usa tal cual (si es jpg/png)
                    datos = _recortar_cuadrado(datos, self.ffmpeg) if self.ffmpeg else datos
            except Exception as e:
                self.log(f"   Carátula no disponible: {_mensaje_corto(e)}")
                datos = None
            self._cache[clave] = datos if _tipo_imagen(datos) else None
        return self._cache[clave]

    def para(self, track: Track, info: dict | None) -> bytes | None:
        """Carátula de Spotify (oEmbed) o, si falla, miniatura de YouTube cuadrada."""
        if track.spotify_id:
            try:
                oembed = json.loads(_leer_url(
                    "https://open.spotify.com/oembed?url=https://open.spotify.com/track/"
                    + track.spotify_id))
                url = oembed.get("thumbnail_url") if isinstance(oembed, dict) else None
            except Exception:
                url = None   # se prueba con la miniatura de YouTube
            if url:
                # oEmbed da 300x300; el mismo id con este prefijo es la versión 640x640
                grande = url.replace("ab67616d00001e02", "ab67616d0000b273")
                datos = (self._imagen(grande, cuadrar=False) if grande != url else None) \
                    or self._imagen(url, cuadrar=False)
                if datos:
                    return datos
        miniatura = (info or {}).get("thumbnail")
        return self._imagen(miniatura, cuadrar=True) if miniatura else None


# ── Etiquetas ───────────────────────────────────────────────────────────────

def etiquetar(ruta: Path, track: Track, album: str, posicion: int, total: int,
              portada: bytes | None = None) -> bool:
    """
    Escribe las etiquetas en un .mp3 (ID3v2.3) o .m4a (MP4). `album` (nombre de
    la playlist) se usa si la canción no trae álbum propio. Devuelve False si el
    formato no admite etiquetas (p. ej. .webm). Los errores se relanzan.
    """
    ruta = Path(ruta)
    ext = ruta.suffix.lower()
    if ext not in (".mp3", ".m4a"):
        return False
    artista = track.artist
    nombre_album = track.album or album
    if track.album:
        artista_album = track.artists[0] if track.artists else ""
    else:
        artista_album = ARTISTA_VARIOS if album else ""
    mime = _tipo_imagen(portada)

    if ext == ".mp3":
        from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TIT2, TPE1, TPE2, TRCK

        try:
            tags = ID3(ruta)
        except ID3NoHeaderError:
            tags = ID3()
        tags.add(TIT2(encoding=3, text=track.title))
        if artista:
            tags.add(TPE1(encoding=3, text=artista))
        if nombre_album:
            tags.add(TALB(encoding=3, text=nombre_album))
        if artista_album:
            tags.add(TPE2(encoding=3, text=artista_album))
        tags.add(TRCK(encoding=3, text=f"{posicion}/{total}"))
        if mime:
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=portada))
        # v2.3: la que mejor leen el Explorador de Windows y los reproductores antiguos
        tags.save(ruta, v2_version=3)
    else:
        from mutagen.mp4 import MP4, MP4Cover

        audio = MP4(ruta)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        tags["\xa9nam"] = [track.title]
        if artista:
            tags["\xa9ART"] = [artista]
        if nombre_album:
            tags["\xa9alb"] = [nombre_album]
        if artista_album:
            tags["aART"] = [artista_album]
        tags["trkn"] = [(posicion, total)]
        if mime:
            tipo = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            tags["covr"] = [MP4Cover(portada, imageformat=tipo)]
        audio.save()
    return True


def _etiquetar_seguro(info: dict | None, folder: Path, stem: str, formato: str, track: Track,
                      album: str, posicion: int, total: int, portadas: _Portadas,
                      log: Callable[[str], None]) -> None:
    """Etiqueta el archivo descargado; cualquier error solo se anota en el log."""
    try:
        ruta = _archivo_final(info, folder, stem, formato)
        if not ruta or ruta.suffix.lower() not in (".mp3", ".m4a"):
            return   # p. ej. .webm sin ffmpeg: sin etiquetas
        etiquetar(ruta, track, album, posicion, total, portadas.para(track, info))
    except Exception as e:
        log(f"   No se pudieron escribir las etiquetas de {stem}: {_mensaje_corto(e)}")


# ── Sincronización: manifiesto, renumeración y quitadas ─────────────────────

_RE_PREFIJO = re.compile(r"^(\d+) - ")


def renumerar_etiqueta(ruta: Path, posicion: int, total: int) -> bool:
    """Cambia solo el número de pista (TRCK / trkn) de un .mp3 o .m4a. Los errores se relanzan."""
    ruta = Path(ruta)
    ext = ruta.suffix.lower()
    if ext == ".mp3":
        from mutagen.id3 import ID3, ID3NoHeaderError, TRCK

        try:
            tags = ID3(ruta)
        except ID3NoHeaderError:
            tags = ID3()
        tags.add(TRCK(encoding=3, text=f"{posicion}/{total}"))
        tags.save(ruta, v2_version=3)
        return True
    if ext == ".m4a":
        from mutagen.mp4 import MP4

        audio = MP4(ruta)
        if audio.tags is None:
            audio.add_tags()
        audio.tags["trkn"] = [(posicion, total)]
        audio.save()
        return True
    return False


def _ext_preferida(exts: set[str], formato: str) -> str:
    return f".{formato}" if f".{formato}" in exts else sorted(exts)[0]


def _mover(origen: Path, destino: Path, stem_de: str, stem_a: str, exts: list[str]) -> bool:
    """Renombra/mueve todos los archivos stem_de.<ext>; si uno falla, deshace los demás."""
    hechos = []
    try:
        for ext in exts:
            (origen / f"{stem_de}{ext}").rename(destino / f"{stem_a}{ext}")
            hechos.append(ext)
    except OSError:
        for ext in hechos:
            try:
                (destino / f"{stem_a}{ext}").rename(origen / f"{stem_de}{ext}")
            except OSError:
                pass
        return False
    return True


def _renombrar(folder: Path, cambios: list[tuple[str, str]], existentes: dict[str, set[str]],
               log: Callable[[str], None]) -> dict[str, str]:
    """
    Aplica los cambios de nombre (stem actual -> stem nuevo, con todas sus
    extensiones de audio) en dos pasadas: primero a nombres temporales y luego
    a los definitivos, así dos canciones pueden intercambiar su número sin
    pisarse. Si el nombre nuevo lo ocupa otro archivo, se deja el antiguo.
    Devuelve stem actual -> stem final y actualiza `existentes`.
    """
    temporales = []
    for n, (de, a) in enumerate(cambios):
        exts = sorted(existentes.get(de, ()))
        tmp = f".spotyurl-renombrando-{n}"
        if _mover(folder, folder, de, tmp, exts):
            existentes.pop(de, None)
            temporales.append((de, a, exts, tmp))
        else:
            log(f"   No se pudo renumerar {de}")
    finales: dict[str, str] = {}
    for de, a, exts, tmp in temporales:
        candidatos = [a, de] + [f"{de} ({k})" for k in range(2, 100)]
        for destino in candidatos:
            if any((folder / f"{destino}{ext}").exists() for ext in exts):
                if destino == a:
                    log(f"   No se puede renumerar {de}: ya existe otro archivo «{a}»")
                continue
            if _mover(folder, folder, tmp, destino, exts):
                finales[de] = destino
                existentes[destino] = set(exts)
                break
    return finales


def _adoptar_antiguos(tracks: list[Track], sin_archivo: list[int], existentes: dict[str, set[str]],
                      ocupados: set[str], deseados: dict[int, str]) -> dict[int, str]:
    """
    Carpetas anteriores al manifiesto (o archivos sin registrar): empareja los
    archivos "NN - Artista - Título" con las canciones por el nombre sin el
    número. Devuelve índice de la canción -> stem del archivo adoptado.
    """
    indice: dict[str, list[str]] = {}
    for stem in existentes:
        m = _RE_PREFIJO.match(stem)
        if m and stem not in ocupados:
            indice.setdefault(stem[m.end():].casefold(), []).append(stem)
    adoptados: dict[int, str] = {}
    usados: set[str] = set()
    for i in sin_archivo:
        label = tracks[i].label
        # Con nombres largos, safe_filename recorta: se prueba con prefijos de varios anchos
        restos = {safe_filename(label).casefold()}
        restos |= {safe_filename(f"{'0' * w} - {label}")[w + 3:].casefold() for w in range(1, 6)}
        candidatos = sorted({s for r in restos for s in indice.get(r, ()) if s not in usados})
        candidatos = [s for s in candidatos
                      if safe_filename(f"{_RE_PREFIJO.match(s).group(1)} - {label}").casefold()
                      == s.casefold()]
        if not candidatos:
            continue
        elegido = deseados[i] if deseados[i] in candidatos else candidatos[0]
        adoptados[i] = elegido
        usados.add(elegido)
    return adoptados


def _entrada(track: Track, archivo: str, previa: dict | None = None) -> dict:
    """Entrada del manifiesto para la canción (conserva el enlace de la previa si lo hay)."""
    entrada = dict(previa or {})
    if not entrada.get("youtube_url"):
        entrada.update(youtube_url=track.youtube_url, youtube_titulo=track.youtube_title,
                       manual=track.status == Status.MANUAL)
    entrada.update(archivo=archivo, titulo=track.title, artista=track.artist)
    entrada.setdefault("manual", False)
    return entrada


def escribir_m3u8(folder: Path, nombre: str, entradas: list[tuple[Track, str]]) -> Path | None:
    """
    Lista local <nombre>.m3u8 (UTF-8) con rutas relativas a los archivos de la
    carpeta, en el orden de `entradas` (track, nombre de archivo). None si no hay ninguna.
    """
    if not entradas:
        return None
    lineas = ["#EXTM3U"]
    for track, archivo in entradas:
        lineas.append(f"#EXTINF:{track.duration_s or -1},{track.label}")
        lineas.append(archivo)
    ruta = Path(folder) / f"{safe_filename(nombre) or 'Lista de canciones'}.m3u8"
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def download_tracks(
    tracks: list[Track],
    folder: Path,
    on_progress: Callable[[int, int], None] | None = None,   # (hechas, total)
    on_log: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
    formato: str = "mp3",   # clave de FORMATOS_AUDIO
    album: str = "",        # álbum de las canciones sin álbum propio (nombre de la playlist)
    on_track: Callable[[int, str, float], None] | None = None,   # (índice 0-based, estado, %)
    origen: str = "",       # enlace de Spotify de la lista (se guarda en el manifiesto)
    mover_quitadas: bool = False,   # mover a «Quitadas/» las que ya no están en la lista
    lista_m3u: bool = True,         # escribir <nombre>.m3u8 con los archivos de la carpeta
) -> DownloadResult:
    """
    Descarga y etiqueta el audio de las canciones con enlace. No relanza al
    cancelar. on_track recibe el índice de la canción en `tracks`, uno de
    ESTADOS_AUDIO y el porcentaje (solo significativo en "descargando"). Al
    cancelar, la canción en curso vuelve a "cola".

    Sincronización: el manifiesto de la carpeta (.spotyurl.json) dice qué
    archivo es cada canción. Las ya descargadas no se vuelven a descargar
    aunque cambie su posición: se renombran al número nuevo (result.renamed).
    Las del manifiesto que ya no están en `tracks` van a result.removed (y, con
    mover_quitadas, a la subcarpeta «Quitadas»). Carpetas sin manifiesto: los
    archivos "NN - Artista - Título" se adoptan por nombre.
    """
    if formato not in FORMATOS_AUDIO:
        raise ValueError(f"Formato de audio no soportado: {formato}")
    log = on_log or (lambda _msg: None)
    aviso = on_track or (lambda _i, _estado, _pct: None)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = DownloadResult()

    # La posición se calcula sobre la lista completa para que sea estable
    pendientes = [(i, t) for i, t in enumerate(tracks, 1) if t.youtube_url]
    total = len(pendientes)
    previo = leer_manifiesto(folder)
    if not total and previo is None:
        return result
    for pos, _track in pendientes:
        aviso(pos - 1, ESTADO_COLA, 0.0)

    ffmpeg = ffmpeg_path()
    if not ffmpeg and total:
        log("ffmpeg no encontrado: el audio se guardará en su formato original (.m4a/.webm). "
            "Vuelve a ejecutar instalar para obtener .mp3.")

    manifiesto = previo or nuevo_manifiesto()
    nombre = album or folder.name
    total_previo = manifiesto.get("total")
    manifiesto.update(origen=origen or manifiesto.get("origen") or "", nombre=nombre, formato=formato,
                      total=len(tracks))
    canciones: dict[str, dict] = manifiesto["canciones"]
    claves = claves_unicas(tracks)
    existentes = _existentes(folder)
    deseados = {i: nombre_archivo(i + 1, len(tracks), t) for i, t in enumerate(tracks)}

    def guardar() -> None:
        try:
            guardar_manifiesto(folder, manifiesto)
        except OSError as e:
            log(f"   No se pudo guardar el manifiesto de la carpeta: {_mensaje_corto(e)}")

    # 1. Archivo actual de cada canción: el del manifiesto o, si no, uno antiguo con su nombre
    stem_de = {clave: Path(e["archivo"]).stem for clave, e in canciones.items()}
    actuales: dict[int, str] = {}
    for i, clave in enumerate(claves):
        stem = stem_de.get(clave)
        if stem in existentes and stem not in actuales.values():
            actuales[i] = stem
    ocupados = {s for s in stem_de.values() if s in existentes}
    sin_archivo = [i for i in range(len(tracks)) if i not in actuales]
    actuales.update(_adoptar_antiguos(tracks, sin_archivo, existentes, ocupados, deseados))

    # 2. Quitadas: en el manifiesto pero ya no en la lista
    en_lista = set(claves)
    for clave in [c for c in canciones if c not in en_lista]:
        stem = stem_de[clave]
        exts = existentes.get(stem)
        if not exts:
            del canciones[clave]   # el archivo ya no está: nada que recordar
            continue
        archivo = stem + _ext_preferida(exts, formato)
        result.removed.append(archivo)
        if not mover_quitadas:
            log(f"Ya no está en la lista: {archivo}")
            continue
        quitadas = folder / CARPETA_QUITADAS
        try:
            quitadas.mkdir(exist_ok=True)
            destino = unique_path(quitadas / archivo).stem
            ok = _mover(folder, quitadas, stem, destino, sorted(exts))
        except OSError:
            ok = False
        if ok:
            del canciones[clave]
            existentes.pop(stem, None)
            log(f"Movida a {CARPETA_QUITADAS}: {archivo}")
        else:
            log(f"   No se pudo mover a {CARPETA_QUITADAS}: {archivo}")

    # 3. Renumerar las que cambiaron de posición (en dos pasadas, sin colisiones)
    cambios = [(actuales[i], deseados[i]) for i in sorted(actuales) if actuales[i] != deseados[i]]
    finales = _renombrar(folder, cambios, existentes, log) if cambios else {}
    for i in sorted(actuales):
        viejo = actuales[i]
        nuevo = finales.get(viejo, viejo)
        if nuevo not in existentes:   # no se pudo renombrar ni devolver a su sitio
            del actuales[i]
            continue
        actuales[i] = nuevo
        exts = existentes[nuevo]
        archivo = nuevo + _ext_preferida(exts, formato)
        if nuevo != viejo:
            antes = viejo + _ext_preferida(exts, formato)
            result.renamed.append((antes, archivo))
            log(f"Renumerada: {antes} -> {archivo}")
        # Número de pista "n/total": cambia al renumerar y también si cambia el total
        if nuevo != viejo or total_previo != len(tracks) or claves[i] not in canciones:
            for ext in sorted(exts & {".mp3", ".m4a"}):
                try:
                    renumerar_etiqueta(folder / f"{nuevo}{ext}", i + 1, len(tracks))
                except Exception as e:
                    log(f"   No se pudo cambiar el número de pista de {nuevo}{ext}: {_mensaje_corto(e)}")
        canciones[claves[i]] = _entrada(tracks[i], archivo, canciones.get(claves[i]))
    guardar()

    portadas = _Portadas(ffmpeg, log)
    actual = {"indice": 0, "ultimo": 0.0}   # canción en curso y último aviso de %

    def hook(d: dict) -> None:
        if cancel and cancel.is_set():
            raise DescargaCancelada()
        estado = d.get("status")
        if estado == "downloading":
            ahora = time.monotonic()
            tam = d.get("total_bytes") or d.get("total_bytes_estimate")
            if tam and ahora - actual["ultimo"] >= INTERVALO_PROGRESO:
                actual["ultimo"] = ahora
                pct = 100.0 * (d.get("downloaded_bytes") or 0) / tam
                aviso(actual["indice"], ESTADO_DESCARGANDO, min(100.0, pct))
        elif estado == "finished" and ffmpeg:
            aviso(actual["indice"], ESTADO_CONVIRTIENDO, 100.0)

    try:
        for hechas, (pos, track) in enumerate(pendientes, 1):
            if cancel and cancel.is_set():
                log("Descarga cancelada.")
                break
            indice = pos - 1
            stem = actuales.get(indice) or deseados[indice]
            ya = existentes.get(stem, set())
            # Con ffmpeg solo cuenta el formato elegido (cambiar de formato vuelve a descargar)
            if (f".{formato}" in ya) if ffmpeg else ya:
                result.skipped.append(track)
                aviso(indice, ESTADO_EXISTE, 100.0)
                log(f"[{hechas}/{total}] Ya existe: {stem}")
            else:
                actual["indice"], actual["ultimo"] = indice, time.monotonic()
                aviso(indice, ESTADO_DESCARGANDO, 0.0)
                try:
                    info = _descargar_una(track.youtube_url, _opciones(folder, stem, ffmpeg, formato, hook), cancel)
                except Exception as e:
                    if isinstance(e, DescargaCancelada) or (cancel and cancel.is_set()):
                        aviso(indice, ESTADO_COLA, 0.0)
                        log("Descarga cancelada.")
                        break
                    motivo = _mensaje_corto(e)
                    result.failed.append((track, motivo))
                    aviso(indice, ESTADO_ERROR, 0.0)
                    log(f"[{hechas}/{total}] Error: {track.label} — {motivo}")
                else:
                    aviso(indice, ESTADO_ETIQUETANDO, 100.0)
                    _etiquetar_seguro(info, folder, stem, formato, track, album, pos, len(tracks),
                                      portadas, log)
                    ruta = _archivo_final(info, folder, stem, formato)
                    ext = ruta.suffix.lower() if ruta else f".{formato}"
                    existentes.setdefault(stem, set()).add(ext)
                    actuales[indice] = stem
                    # Se registra al momento: una cancelación no pierde lo ya descargado.
                    # El enlace guardado es el del archivo que hay ahora en la carpeta.
                    canciones[claves[indice]] = _entrada(track, stem + ext)
                    guardar()
                    result.ok.append(track)
                    aviso(indice, ESTADO_OK, 100.0)
                    log(f"[{hechas}/{total}] Descargada: {stem}")
            if on_progress:
                on_progress(hechas, total)
    finally:
        # 4. Manifiesto y lista local con lo que haya en la carpeta (también si se canceló)
        for i, stem in actuales.items():
            if stem in existentes and claves[i] in canciones:
                canciones[claves[i]]["archivo"] = stem + _ext_preferida(existentes[stem], formato)
        guardar()
        if lista_m3u:
            entradas = [(tracks[i], canciones[claves[i]]["archivo"]) for i in sorted(actuales)
                        if actuales[i] in existentes and claves[i] in canciones]
            try:
                escribir_m3u8(folder, nombre, entradas)
            except OSError as e:
                log(f"   No se pudo escribir la lista .m3u8: {_mensaje_corto(e)}")
    return result


