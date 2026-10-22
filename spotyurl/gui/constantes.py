"""Constantes de la interfaz gráfica (hoja: no importa otros módulos de gui)."""

import re
from pathlib import Path

from ..models import Status
from ..paths import cache_path

CACHE_PATH = cache_path()
ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "icon.svg"
RE_YOUTUBE = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/)|youtu\.be/)([\w-]{11})")

COLOR_ESTADO = {
    Status.PENDING: "#8a8f98",
    Status.SEARCHING: "#3b82f6",
    Status.OK: "#1db954",
    Status.DOUBTFUL: "#f5a524",
    Status.FAILED: "#f04461",
    Status.MANUAL: "#a970ff",
}
