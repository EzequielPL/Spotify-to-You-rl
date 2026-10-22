"""Constantes de la interfaz gráfica (hoja: no importa otros módulos de gui)."""

import re
from pathlib import Path

from ..models import Status
from ..paths import cache_path

CACHE_PATH = cache_path()
ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "icon.svg"
RE_YOUTUBE = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/)|youtu\.be/)([\w-]{11})")

# Texto del estado en la interfaz (Status.FAILED vale "sin match" en el núcleo)
ETIQUETA_ESTADO = {s: s.value for s in Status} | {Status.FAILED: "sin enlace"}


def plural(n: int, singular: str, plural_: str | None = None) -> str:
    """plural(1, "canción", "canciones") → "1 canción"; plural(3, …) → "3 canciones"."""
    return f"{n} {singular if n == 1 else plural_ or singular + 's'}"
