"""
Actualización de yt-dlp desde la app (sin Qt).

YouTube cambia a menudo y los errores más frecuentes al descargar (HTTP 403,
«nsig», «not a bot») se arreglan con una versión nueva de yt-dlp. Este módulo
solo calcula qué versión hay y qué comando la actualiza; quien lo ejecuta es
la interfaz (gui/dialogo_actualizar.py).
"""

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

# A partir de cuántos días se avisa al arrancar de que yt-dlp está desfasado
DIAS_AVISO = 60

_RE_VERSION = re.compile(r"^\s*(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.|$)")
_RE_VERSION_PY = re.compile(r"""^__version__\s*=\s*['"]([^'"]+)['"]""", re.M)


def version_ytdlp() -> str:
    """
    Versión de yt-dlp instalada ("" si no está). Sin importar el paquete
    yt_dlp entero (lento): lee yt_dlp/version.py tal cual.
    """
    mod = sys.modules.get("yt_dlp.version")
    if mod is not None:
        return str(getattr(mod, "__version__", ""))
    try:
        spec = importlib.util.find_spec("yt_dlp")   # no ejecuta yt_dlp/__init__.py
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.origin:
        try:
            m = _RE_VERSION_PY.search((Path(spec.origin).parent / "version.py").read_text(encoding="utf-8"))
            if m:
                return m.group(1)
        except OSError:
            pass
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("yt-dlp")
    except (ImportError, PackageNotFoundError):
        return ""


def fecha_version(v: str) -> date | None:
    """«2026.08.19» o «2026.8.19.1» -> date(2026, 8, 19); None si no es una fecha."""
    m = _RE_VERSION.match(v or "")
    if not m:
        return None
    try:
        return date(*map(int, m.groups()))
    except ValueError:
        return None


def dias_desde_version(v: str, hoy: date | None = None) -> int | None:
    """Días transcurridos desde la fecha de la versión (None si no se entiende)."""
    f = fecha_version(v)
    if f is None:
        return None
    return max(0, ((hoy or date.today()) - f).days)


def python_consola(ejecutable: str | None = None) -> str:
    """
    El intérprete con consola: en Windows, pythonw.exe no tiene stdout y pip
    lo necesita, así que se usa el python.exe de la misma carpeta.
    """
    exe = ejecutable or sys.executable
    p = Path(exe)
    if p.name.lower() == "pythonw.exe":
        return str(p.with_name("python.exe"))
    return exe


def comando_actualizar(ejecutable: str | None = None) -> list[str]:
    """Comando que actualiza yt-dlp en el entorno de la app."""
    return [python_consola(ejecutable), "-m", "pip", "install", "--upgrade", "yt-dlp[default]"]


def comando_version(ejecutable: str | None = None) -> list[str]:
    """
    Comando que imprime la versión instalada en disco (tras actualizar, el
    módulo ya importado en memoria sigue siendo el antiguo).
    """
    return [python_consola(ejecutable), "-c", "import yt_dlp.version as v; print(v.__version__)"]
