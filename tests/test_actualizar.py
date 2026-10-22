"""Pruebas de spotyurl.actualizar (sin Qt ni red; nunca ejecuta pip)."""

import sys
from datetime import date

import pytest

from spotyurl import actualizar

HOY = date(2026, 10, 22)


@pytest.mark.parametrize("version, dias", [
    ("2026.08.19", 64),
    ("2026.8.19", 64),
    ("2026.8.19.1", 64),
    ("2026.08.19.232813.dev0", 64),   # nightly
    ("2026.10.22", 0),
    ("2026.12.01", 0),                # fecha futura: no negativa
])
def test_dias_desde_version(version, dias):
    assert actualizar.dias_desde_version(version, HOY) == dias


@pytest.mark.parametrize("version", ["", "abc", "1.2.3", "2026.13.01", "2026.02.30", "2026-08-19", "2026.08"])
def test_dias_desde_version_invalida(version):
    assert actualizar.dias_desde_version(version, HOY) is None


def test_comando_usa_python_con_consola(tmp_path):
    pythonw = tmp_path / "Scripts" / "pythonw.exe"
    cmd = actualizar.comando_actualizar(str(pythonw))
    assert cmd == [str(pythonw.with_name("python.exe")), "-m", "pip", "install", "--upgrade", "yt-dlp[default]"]
    assert actualizar.comando_version(str(pythonw))[0] == str(pythonw.with_name("python.exe"))
    python = str(tmp_path / "bin" / "python3")
    assert actualizar.comando_actualizar(python)[0] == python


def test_comando_por_defecto_es_el_interprete_actual(monkeypatch):
    monkeypatch.setattr(sys, "executable", "/opt/venv/bin/python")
    assert actualizar.comando_actualizar()[:3] == ["/opt/venv/bin/python", "-m", "pip"]


def test_version_ytdlp_sin_importar_el_paquete(monkeypatch):
    pytest.importorskip("yt_dlp")
    monkeypatch.delitem(sys.modules, "yt_dlp.version", raising=False)
    v = actualizar.version_ytdlp()
    assert actualizar.fecha_version(v) is not None
    monkeypatch.setitem(sys.modules, "yt_dlp.version", type("M", (), {"__version__": "2001.01.01"}))
    assert actualizar.version_ytdlp() == "2001.01.01"   # el ya importado manda
