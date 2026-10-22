"""Rutas de la app (datos, música, proyecto) y nombres de archivo seguros."""

import os
import re
import sys
from pathlib import Path

# Raíz del repositorio (la carpeta que contiene el paquete spotyurl)
CARPETA_PROYECTO = Path(__file__).resolve().parent.parent
# Carpeta por defecto de los .txt/.csv/.m3u
CARPETA_ENLACES = CARPETA_PROYECTO / "enlaces"


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


def cache_path() -> Path:
    """Caché de búsquedas de YouTube (compartida por la CLI y la UI)."""
    return app_data_dir() / "search_cache.json"
