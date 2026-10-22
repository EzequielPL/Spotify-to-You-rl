"""Comportamiento dependiente del sistema operativo (Windows / macOS / Linux)."""

import os
import sys
from pathlib import Path

import pytest

from spotyurl import paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


def test_app_data_dir_macos(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths.app_data_dir() == home / "Library" / "Application Support" / "spotyurl"


def test_app_data_dir_windows(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    assert paths.app_data_dir() == home / "AppData" / "Roaming" / "spotyurl"


def test_app_data_dir_linux(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert paths.app_data_dir() == home / ".config" / "spotyurl"
    assert paths.app_data_dir().is_dir()


# ── UI: se construye sin pantalla (QT_QPA_PLATFORM=offscreen) ────────────────

def test_ventana_principal_se_construye(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from spotyurl import gui

    app = QApplication.instance() or QApplication([])
    gui.aplicar_tema(app, "dark")
    w = gui.MainWindow()
    assert not QIcon(str(gui.ICON_PATH)).isNull()
    w.url.setText("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
    assert w.btn_convertir.isEnabled()
    w.close()


def test_dialogo_ajustes_se_construye(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from spotyurl import gui

    app = QApplication.instance() or QApplication([])
    ajustes = gui.Ajustes(QSettings(str(tmp_path / "ajustes.ini"), QSettings.IniFormat))
    d = gui.DialogoAjustes(ajustes)
    assert d.carpeta.text() == gui.DEFAULTS["out_dir"]
    d.close()


# ── Rutas del proyecto y migración de ajustes ────────────────────────────────

def test_icono_existe():
    from spotyurl.gui.constantes import ICON_PATH

    assert ICON_PATH.is_file()


def test_carpeta_proyecto():
    assert (paths.CARPETA_PROYECTO / "pyproject.toml").is_file()
    assert paths.CARPETA_ENLACES == paths.CARPETA_PROYECTO / "enlaces"


def test_cache_path(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert paths.cache_path() == home / ".config" / "spotyurl" / "search_cache.json"


def test_migracion_out_dir(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QSettings

    from spotyurl.gui.ajustes import DEFAULTS, Ajustes

    a = Ajustes(QSettings(str(tmp_path / "ajustes.ini"), QSettings.IniFormat))
    assert DEFAULTS["out_dir"] == str(paths.CARPETA_ENLACES)
    assert a["out_dir"] == DEFAULTS["out_dir"]                  # sin valor guardado
    a["out_dir"] = str(paths.CARPETA_PROYECTO)                   # default antiguo
    assert a["out_dir"] == DEFAULTS["out_dir"]
    a["out_dir"] = str(paths.CARPETA_PROYECTO / "sub" / "..")    # misma carpeta escrita de otra forma
    assert a["out_dir"] == DEFAULTS["out_dir"]
    a["out_dir"] = str(tmp_path)                                 # elegida por el usuario: se respeta
    assert a["out_dir"] == str(tmp_path)


# ── Integración con red (Spotify real). Solo si SPOTYURL_NETWORK=1 ───────────

@pytest.mark.skipif(os.environ.get("SPOTYURL_NETWORK") != "1", reason="requiere red: SPOTYURL_NETWORK=1")
def test_extraccion_real_de_album():
    from spotyurl.spotify import fetch_tracks

    tracks = fetch_tracks("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy")
    assert len(tracks) == 18
    assert all(t.title and t.artists and t.duration_s for t in tracks)


def test_music_dir_usa_musica(home):
    (home / "Music").mkdir()
    (home / "Desktop").mkdir()
    assert paths.music_dir() == home / "Music"


def test_music_dir_sin_musica_usa_escritorio(home):
    (home / "Desktop").mkdir()
    assert paths.music_dir() == home / "Desktop"
    (home / "Desktop").rmdir()
    assert paths.music_dir() == home
