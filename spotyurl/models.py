"""Modelo de datos compartido por la CLI y la UI."""

import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path



class Status(str, Enum):
    PENDING = "pendiente"
    SEARCHING = "buscando"
    OK = "encontrada"
    DOUBTFUL = "dudosa"
    FAILED = "sin match"
    MANUAL = "manual"


@dataclass
class Track:
    title: str
    artists: list[str] = field(default_factory=list)
    duration_s: int | None = None
    album: str = ""
    spotify_id: str = ""
    youtube_url: str = ""
    youtube_title: str = ""
    score: float | None = None
    status: Status = Status.PENDING

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)

    @property
    def label(self) -> str:
        return f"{self.artist} - {self.title}" if self.artists else self.title

    @property
    def has_link(self) -> bool:
        return bool(self.youtube_url)


def fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_duration(text: str) -> int | None:
    """'3:43' -> 223, '1:02:03' -> 3723. None si no es una duración."""
    parts = text.strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total


_RE_SEPARADORES = re.compile(r"[/\\]")
_RE_INVALIDOS = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(name: str, max_len: int = 120) -> str:
    """
    Convierte un texto en un nombre de archivo o carpeta válido en Windows,
    macOS y Linux: 'AC/DC: Back in Black?' -> 'AC-DC Back in Black'.
    Devuelve "" si no queda nada utilizable.
    """
    name = _RE_INVALIDOS.sub("", _RE_SEPARADORES.sub("-", name))
    name = re.sub(r"\s+", " ", name).strip()[:max_len].strip().rstrip(". ")
    if name.split(".")[0].upper() in _RESERVADOS:
        name = f"_{name}"
    return name


def music_dir() -> Path:
    """
    Carpeta de música del usuario (~/Music en Windows y macOS). Si no existe,
    el Escritorio y, en último caso, la carpeta personal.
    """
    for carpeta in (Path.home() / "Music", Path.home() / "Desktop"):
        if carpeta.is_dir():
            return carpeta
    return Path.home()


def app_data_dir() -> Path:
    """
    Carpeta de datos de la app:
      Windows  %APPDATA%\\spotyurl
      macOS    ~/Library/Application Support/spotyurl
      Linux    $XDG_CONFIG_HOME/spotyurl (o ~/.config/spotyurl)
    """
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / "spotyurl"
    path.mkdir(parents=True, exist_ok=True)
    return path
