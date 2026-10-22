"""Ajustes persistentes de la interfaz (QSettings)."""

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, QStandardPaths

from ..paths import CARPETA_ENLACES, CARPETA_PROYECTO, music_dir


DEFAULTS = {
    "clipboard": False,   # copiar cada enlace al portapapeles (MediaHuman)
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
    # Estado de la ventana
    "input_mode": 0,      # 0 = enlace de Spotify, 1 = lista de texto
    "log_open": False,
    "header_cols": 0,     # columnas de la tabla al guardar ui/header (si cambian, no se restaura)
}


MAX_RECIENTES = 10
CLAVE_RECIENTES = "recientes"   # JSON: [{"url", "nombre", "carpeta", "fecha"}, …], la más reciente primero


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

    # Datos binarios de la ventana (geometría, estado de la cabecera), fuera de DEFAULTS
    def get_bytes(self, key: str) -> QByteArray | None:
        value = self._s.value(key)
        if isinstance(value, (bytes, bytearray)):
            value = QByteArray(bytes(value))
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    def set_bytes(self, key: str, value: QByteArray):
        self._s.setValue(key, value)

    def snapshot(self) -> dict:
        return {k: self[k] for k in DEFAULTS}

    # Listas recientes (menú «Recientes»), fuera de DEFAULTS: no van al snapshot de los hilos
    def recientes(self) -> list[dict]:
        try:
            datos = json.loads(self._s.value(CLAVE_RECIENTES, "") or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(datos, list):
            return []
        limpias = []
        for d in datos:
            if isinstance(d, dict) and isinstance(d.get("url"), str) and d["url"]:
                limpias.append({k: str(d.get(k) or "") for k in ("url", "nombre", "carpeta", "fecha")})
        return limpias[:MAX_RECIENTES]

    def agregar_reciente(self, url: str, nombre: str = "", carpeta: str | Path = "", fecha: str = "") -> None:
        """
        Pone la lista al principio. Sin duplicados: se quita la entrada anterior
        con el mismo enlace o la misma carpeta. Una conversión (sin carpeta) de
        una lista ya descargada conserva la carpeta que tenía.
        """
        if not url:
            return
        carpeta = str(carpeta or "")
        anteriores = self.recientes()
        if not carpeta:
            carpeta = next((r["carpeta"] for r in anteriores if r["url"] == url and r["carpeta"]), "")
        nueva = {"url": url, "nombre": nombre or url, "carpeta": carpeta,
                 "fecha": fecha or datetime.now().isoformat(timespec="minutes")}
        resto = [r for r in anteriores if r["url"] != url and not (carpeta and r["carpeta"] == carpeta)]
        lista = [nueva] + resto
        self._s.setValue(CLAVE_RECIENTES, json.dumps(lista[:MAX_RECIENTES], ensure_ascii=False))

    def borrar_recientes(self) -> None:
        self._s.remove(CLAVE_RECIENTES)
