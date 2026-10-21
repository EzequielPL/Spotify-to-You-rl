"""Exportación de resultados a .txt (MediaHuman), .csv y .m3u."""

import csv
from datetime import datetime
from pathlib import Path

from .models import Track, fmt_duration, safe_filename


FORMATOS = {
    "txt": "Enlaces (*.txt)",
    "csv": "Hoja de cálculo (*.csv)",
    "m3u": "Lista M3U (*.m3u)",
}


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
        w.writerow(["#", "titulo", "artista", "album", "duracion", "estado",
                    "puntuacion", "youtube_url", "youtube_titulo", "spotify_id"])
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
