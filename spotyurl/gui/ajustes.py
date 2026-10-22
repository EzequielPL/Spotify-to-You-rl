"""Ajustes persistentes de la interfaz (QSettings)."""

from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

from ..paths import CARPETA_ENLACES, CARPETA_PROYECTO, music_dir


DEFAULTS = {
    "clipboard": True,
    "pause": 1.0,
    "headless": True,
    "n_results": 6,
    "query_template": "{artist} - {title}",
    "scroll_pause": 0.7,
    "end_rounds": 8,
    "use_cache": True,
    "auto_save": True,
    "out_dir": str(CARPETA_ENLACES),   # .txt/.csv/.m3u en enlaces/ del proyecto
    # Música del sistema (Windows y macOS); Qt respeta la carpeta si está redirigida (OneDrive)
    "audio_dir": QStandardPaths.writableLocation(QStandardPaths.MusicLocation) or str(music_dir()),
    "audio_format": "mp3",   # clave de download.FORMATOS_AUDIO; se recuerda la última elegida
    "theme": "dark",
}


def _es_carpeta_proyecto(value) -> bool:
    try:
        return bool(value) and Path(value).resolve() == CARPETA_PROYECTO
    except (OSError, TypeError, ValueError):
        return False


class Ajustes:
    def __init__(self, settings: QSettings | None = None):
        # `settings` permite usar otro almacén (p. ej. un .ini en los tests)
        self._s = settings if settings is not None else QSettings("spotyurl", "Spotify to You-rl")

    def __getitem__(self, key):
        default = DEFAULTS[key]
        value = self._s.value(key, default)
        # QSettings en Windows devuelve strings: convertir al tipo del default
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        if isinstance(default, (int, float)):
            try:
                return type(default)(value)
            except (TypeError, ValueError):
                return default
        if key == "out_dir" and _es_carpeta_proyecto(value):
            # Migración: antes el default era la raíz del proyecto; ahora, enlaces/
            return default
        return value

    def __setitem__(self, key, value):
        self._s.setValue(key, value)

    def snapshot(self) -> dict:
        return {k: self[k] for k in DEFAULTS}
