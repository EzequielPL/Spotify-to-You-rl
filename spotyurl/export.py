"""Exportación de resultados a .txt (MediaHuman), .csv y .m3u, e importación de .csv."""

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from .models import Status, Track, fmt_duration, parse_duration
from .paths import safe_filename


FORMATOS = {
    "txt": "Enlaces (*.txt)",
    "csv": "Hoja de cálculo (*.csv)",
    "m3u": "Lista M3U (*.m3u)",
}

# Formatos que se pueden abrir como lista de canciones (from_csv)
IMPORTABLES = {"csv": "Hoja de cálculo (*.csv)"}

CABECERAS_CSV = ["#", "titulo", "artista", "album", "duracion", "estado",
                 "puntuacion", "youtube_url", "youtube_titulo", "spotify_id"]
# Estados que tienen sentido con enlace / sin enlace al importar
_ESTADOS_CON_ENLACE = {Status.OK, Status.DOUBTFUL, Status.MANUAL}
_ESTADOS_SIN_ENLACE = {Status.PENDING, Status.FAILED}
_RE_ID_SPOTIFY = re.compile(r"(?:spotify:track:|open\.spotify\.com/(?:[\w-]+/)?track/)([A-Za-z0-9]+)")


def default_name(ext: str = "txt", name: str = "") -> str:
    """Nombre de la playlist saneado; si no hay, uno con la fecha actual."""
    seguro = safe_filename(name)
    if seguro:
        return f"{seguro}.{ext}"
    return f"youtube_links_{datetime.now():%Y%m%d_%H%M%S}.{ext}"


def unique_path(path: Path) -> Path:
    """Si path ya existe, prueba "Nombre (2).txt", "Nombre (3).txt"… hasta uno libre."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidato = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidato.exists():
            return candidato
        n += 1


def to_txt(tracks: list[Track], path: Path) -> int:
    """Un enlace por línea. Devuelve cuántos se escribieron."""
    urls = [t.youtube_url for t in tracks if t.youtube_url]
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    return len(urls)


def to_csv(tracks: list[Track], path: Path) -> int:
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel lo abre bien
        w = csv.writer(f)
        w.writerow(CABECERAS_CSV)
        for i, t in enumerate(tracks, 1):
            w.writerow([i, t.title, t.artist, t.album, fmt_duration(t.duration_s), t.status.value,
                        "" if t.score is None else t.score, t.youtube_url, t.youtube_title, t.spotify_id])
    return len(tracks)


def to_m3u(tracks: list[Track], path: Path) -> int:
    lines = ["#EXTM3U"]
    n = 0
    for t in tracks:
        if t.youtube_url:
            lines.append(f"#EXTINF:{t.duration_s or -1},{t.label}")
            lines.append(t.youtube_url)
            n += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n


def export(tracks: list[Track], path: Path) -> int:
    ext = path.suffix.lower().lstrip(".")
    writer = {"txt": to_txt, "csv": to_csv, "m3u": to_m3u}.get(ext)
    if not writer:
        raise ValueError(f"Formato no soportado: .{ext}")
    return writer(tracks, path)


# ── Importación de .csv ─────────────────────────────────────────────────────

def _leer_texto(path: Path) -> str:
    """UTF-8 (con o sin BOM) o, si no lo es, la codificación de Excel en Windows."""
    datos = Path(path).read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252", errors="replace")


def _filas(texto: str) -> tuple[set[str], list[dict[str, str]]]:
    """Cabeceras (en minúsculas) y filas del CSV como dicts (separador "," ";" o tabulador)."""
    # El separador se decide por la cabecera (Excel en español guarda con ";"):
    # más fiable que csv.Sniffer cuando los campos llevan comas entre comillas
    cabecera = texto.split("\n", 1)[0]
    separador = max(",;\t", key=cabecera.count)
    lector = csv.reader(io.StringIO(texto, newline=""), delimiter=separador)
    cabeceras = [c.strip().lower() for c in next(lector, [])]
    filas = [{c: (fila[k].strip() if k < len(fila) else "") for k, c in enumerate(cabeceras)}
             for fila in lector if any(campo.strip() for campo in fila)]
    return set(cabeceras), filas


def _duracion(texto: str) -> int | None:
    texto = texto.strip()
    return int(texto) if texto.isdigit() else parse_duration(texto)


def _track_propio(fila: dict[str, str]) -> Track | None:
    """Fila del .csv de to_csv (restaura estado, puntuación y enlace)."""
    titulo = fila.get("titulo", "")
    if not titulo:
        return None
    artista = fila.get("artista", "")
    try:
        puntuacion = float(fila["puntuacion"]) if fila.get("puntuacion") else None
    except ValueError:
        puntuacion = None
    url = fila.get("youtube_url", "")
    try:
        estado = Status(fila.get("estado", ""))
    except ValueError:
        estado = None
    if url:
        estado = estado if estado in _ESTADOS_CON_ENLACE else Status.MANUAL
    else:
        estado = estado if estado in _ESTADOS_SIN_ENLACE else Status.PENDING
    return Track(
        title=titulo,
        artists=[a.strip() for a in artista.split(", ") if a.strip()],
        duration_s=_duracion(fila.get("duracion", "")),
        album=fila.get("album", ""),
        spotify_id=fila.get("spotify_id", ""),
        youtube_url=url,
        youtube_title=fila.get("youtube_titulo", ""),
        score=puntuacion,
        status=estado,
    )


def _track_exportify(fila: dict[str, str]) -> Track | None:
    """Fila del .csv de Exportify (artistas separados por "," o, en versiones nuevas, ";")."""
    titulo = fila.get("track name", "")
    if not titulo:
        return None
    artistas = fila.get("artist name(s)") or fila.get("artist name") or ""
    separador = ";" if ";" in artistas else ","
    ms = fila.get("duration (ms)") or fila.get("track duration (ms)") or ""
    uri = fila.get("track uri") or fila.get("spotify uri") or fila.get("uri") or ""
    m = _RE_ID_SPOTIFY.search(uri)
    spotify_id = m.group(1) if m else ""
    if not spotify_id and re.fullmatch(r"[A-Za-z0-9]{22}", fila.get("spotify id", "")):
        spotify_id = fila["spotify id"]
    return Track(
        title=titulo,
        artists=[a.strip() for a in artistas.split(separador) if a.strip()],
        duration_s=round(int(ms) / 1000) if ms.isdigit() else None,
        album=fila.get("album name", ""),
        spotify_id=spotify_id,
    )


def from_csv(path: Path) -> tuple[str, list[Track]]:
    """
    Lee una lista de canciones de un .csv: el que exporta esta app (to_csv, con
    sus enlaces y estados) o el de Exportify (exportify.net). Devuelve
    (nombre de la lista = nombre del archivo, canciones). ValueError si el
    archivo no tiene las columnas de ninguno de los dos.
    """
    path = Path(path)
    cabeceras, filas = _filas(_leer_texto(path))
    if {"titulo", "artista"} <= cabeceras:
        convertir = _track_propio
    elif "track name" in cabeceras and cabeceras & {"artist name(s)", "artist name"}:
        convertir = _track_exportify
    else:
        raise ValueError(
            f"No se reconocen las columnas de «{path.name}». Se admite el .csv que exporta "
            "esta app (titulo, artista, …) o el de Exportify (Track Name, Artist Name(s), …).")
    tracks = [t for t in map(convertir, filas) if t]
    return path.stem, tracks
