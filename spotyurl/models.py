"""Modelo de datos compartido por la CLI y la UI."""

import os
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


def app_data_dir() -> Path:
    """Carpeta de datos de la app (%APPDATA%\\spotyurl en Windows)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    path = Path(base) / "spotyurl"
    path.mkdir(parents=True, exist_ok=True)
    return path
