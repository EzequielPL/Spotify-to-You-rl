"""
Manifiesto de una carpeta de descargas (.spotyurl.json, oculto).

Recuerda qué archivo corresponde a cada canción de la playlist, con qué enlace
de YouTube se descargó y de qué lista viene. Gracias a él, al volver a
descargar (sincronizar) una playlist que ha cambiado de orden, ha perdido o ha
ganado canciones, solo se descargan las nuevas, las demás se renumeran y las
quitadas se detectan.

    {"version": 1, "origen": "<url de Spotify o ''>", "nombre": "<lista>",
     "formato": "mp3", "actualizado": "<iso>", "total": <canciones de la lista>,
     "canciones": {"<clave>": {"archivo": "01 - A - B.mp3", "youtube_url": "...",
                              "youtube_titulo": "...", "titulo": "B",
                              "artista": "A", "manual": false}}}

La clave de cada canción es "sp:<id de Spotify>" o, si no lo tiene (listas de
texto), "tx:<artista|título normalizados>".
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from .models import Status, Track
from .youtube import normalizar

ARCHIVO_MANIFIESTO = ".spotyurl.json"
VERSION_MANIFIESTO = 1
_FILE_ATTRIBUTE_HIDDEN = 0x2


def clave_track(track: Track) -> str:
    """Identificador estable de la canción: su id de Spotify o artista|título normalizados."""
    if track.spotify_id:
        return f"sp:{track.spotify_id}"
    return f"tx:{normalizar(track.artist)}|{normalizar(track.title)}"


def claves_unicas(tracks: list[Track]) -> list[str]:
    """
    Clave de cada canción de la lista. Si una canción se repite en la playlist,
    la segunda aparición lleva "#2", la tercera "#3"… (cada una tiene su archivo).
    """
    vistas: dict[str, int] = {}
    claves = []
    for t in tracks:
        base = clave_track(t)
        vistas[base] = vistas.get(base, 0) + 1
        claves.append(base if vistas[base] == 1 else f"{base}#{vistas[base]}")
    return claves


def nuevo_manifiesto(origen: str = "", nombre: str = "", formato: str = "mp3") -> dict:
    return {"version": VERSION_MANIFIESTO, "origen": origen, "nombre": nombre,
            "formato": formato, "actualizado": "", "total": 0, "canciones": {}}


def ruta_manifiesto(folder: Path) -> Path:
    return Path(folder) / ARCHIVO_MANIFIESTO


def leer_manifiesto(folder: Path) -> dict | None:
    """Manifiesto de la carpeta, o None si no existe o está corrupto."""
    try:
        datos = json.loads(ruta_manifiesto(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict):
        return None
    manifiesto = nuevo_manifiesto()
    manifiesto.update(datos)
    canciones = manifiesto.get("canciones")
    # Se descartan las entradas rotas (sin archivo)
    manifiesto["canciones"] = {
        str(k): v for k, v in (canciones.items() if isinstance(canciones, dict) else ())
        if isinstance(v, dict) and isinstance(v.get("archivo"), str) and v["archivo"]
    }
    for campo in ("origen", "nombre", "formato"):
        if not isinstance(manifiesto.get(campo), str):
            manifiesto[campo] = nuevo_manifiesto()[campo]
    return manifiesto


def _ocultar(ruta: Path) -> None:
    """En Windows marca el archivo como oculto (en macOS/Linux ya lo es por empezar por '.')."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(ruta), _FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def guardar_manifiesto(folder: Path, data: dict) -> None:
    """Escritura atómica (.tmp + replace): un cierre a medias no deja el JSON corrupto."""
    ruta = ruta_manifiesto(folder)
    data["version"] = VERSION_MANIFIESTO
    data["actualizado"] = datetime.now().isoformat(timespec="seconds")
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)
    _ocultar(ruta)   # replace quita el atributo oculto en Windows


def aplicar_manifiesto(tracks: list[Track], manifiesto: dict) -> int:
    """
    Rellena el enlace de YouTube de las canciones que ya están en el manifiesto
    (las descargadas antes), para que solo haya que buscar las nuevas. Queda
    como MANUAL si se eligió a mano y como OK si no. No toca las que ya son
    MANUAL (la elección del usuario manda). Devuelve cuántas se rellenaron.
    """
    canciones = (manifiesto or {}).get("canciones") or {}
    n = 0
    for track, clave in zip(tracks, claves_unicas(tracks)):
        entrada = canciones.get(clave) or canciones.get(clave.split("#")[0])
        if not isinstance(entrada, dict) or not entrada.get("youtube_url"):
            continue
        if track.status == Status.MANUAL and track.youtube_url:
            continue
        track.youtube_url = entrada["youtube_url"]
        if entrada.get("youtube_titulo"):
            track.youtube_title = entrada["youtube_titulo"]
        track.status = Status.MANUAL if entrada.get("manual") else Status.OK
        n += 1
    return n
