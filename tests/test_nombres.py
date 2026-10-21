"""Pruebas de nombres de archivo de salida (sin red)."""

import re

from spotyurl.export import default_name, unique_path


def test_default_name_con_nombre():
    assert default_name("txt", "Mi Playlist") == "Mi Playlist.txt"
    assert default_name("csv", "Rock") == "Rock.csv"


def test_default_name_saneado():
    assert default_name("txt", "AC/DC: Hits?") == "AC-DC Hits.txt"


def test_default_name_sin_nombre():
    patron = r"youtube_links_\d{8}_\d{6}\.txt"
    assert re.fullmatch(patron, default_name())
    assert re.fullmatch(patron, default_name("txt", ""))
    assert re.fullmatch(patron, default_name("txt", "???"))   # no queda nada al sanear


def test_unique_path(tmp_path):
    ruta = tmp_path / "Lista.txt"
    assert unique_path(ruta) == ruta

    ruta.write_text("x")
    segunda = unique_path(ruta)
    assert segunda == tmp_path / "Lista (2).txt"

    segunda.write_text("x")
    assert unique_path(ruta) == tmp_path / "Lista (3).txt"
