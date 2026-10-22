"""Sincronización de carpetas de descarga (manifiesto, renumeración, quitadas, .m3u8) e importación de .csv (sin red)."""

import json
import subprocess
import threading
from pathlib import Path

import pytest

from spotyurl import download
from spotyurl.download import (
    ARCHIVO_MANIFIESTO, CARPETA_QUITADAS, aplicar_manifiesto, clave_track, download_tracks,
    guardar_manifiesto, leer_manifiesto,
)
from spotyurl.export import IMPORTABLES, from_csv, to_csv
from spotyurl.models import Status, Track


def _t(title, sid="", url=None, artist="A", dur=None):
    if url is None:
        url = f"https://www.youtube.com/watch?v={title}"
    return Track(title=title, artists=[artist] if artist else [], spotify_id=sid,
                 youtube_url=url, duration_s=dur)


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr(download, "ffmpeg_path", lambda: None)

    def leer(url):
        raise OSError("sin red")

    monkeypatch.setattr(download, "_leer_url", leer)


@pytest.fixture
def descargas(monkeypatch):
    """Sustituye la descarga: crea el .mp3 con la url como contenido y apunta cada llamada."""
    llamadas = []

    def descargar(url, opts, cancel):
        llamadas.append(url)
        ruta = Path(opts["outtmpl"].replace("%%", "%").replace("%(ext)s", "mp3"))
        ruta.write_bytes(url.encode())
        return {"requested_downloads": [{"filepath": str(ruta)}]}

    monkeypatch.setattr(download, "_descargar_una", descargar)
    return llamadas


def _audio(folder):
    return sorted(p.name for p in folder.iterdir() if p.suffix == ".mp3")


# ── Manifiesto ──────────────────────────────────────────────────────────────

def test_clave_track():
    assert clave_track(_t("B", sid="abc")) == "sp:abc"
    assert clave_track(Track("Canción Ñ!", ["Ártista"])) == "tx:artista|cancion n"


def test_manifiesto_ida_y_vuelta_y_corrupto(tmp_path):
    assert leer_manifiesto(tmp_path) is None
    datos = {"origen": "https://open.spotify.com/playlist/x", "nombre": "Lista", "formato": "m4a",
             "canciones": {"sp:1": {"archivo": "01 - A - B.m4a", "youtube_url": "u", "manual": True}}}
    guardar_manifiesto(tmp_path, datos)
    leido = leer_manifiesto(tmp_path)
    assert leido["version"] == 1 and leido["actualizado"]
    assert leido["origen"] == datos["origen"] and leido["formato"] == "m4a"
    assert leido["canciones"] == datos["canciones"]
    assert not (tmp_path / (ARCHIVO_MANIFIESTO + ".tmp")).exists()
    guardar_manifiesto(tmp_path, leido)   # sobrescribir (también si está oculto en Windows)

    # En Windows un archivo oculto no se puede abrir para escribir: se borra antes
    (tmp_path / ARCHIVO_MANIFIESTO).unlink()
    (tmp_path / ARCHIVO_MANIFIESTO).write_text("{roto", encoding="utf-8")
    assert leer_manifiesto(tmp_path) is None
    (tmp_path / ARCHIVO_MANIFIESTO).write_text('{"canciones": {"x": 3, "y": {"archivo": "a.mp3"}}}',
                                               encoding="utf-8")
    assert list(leer_manifiesto(tmp_path)["canciones"]) == ["y"]


def test_descarga_crea_manifiesto(tmp_path, descargas):
    tracks = [_t("B", "id1"), _t("C", "id2")]
    tracks[1].status = Status.MANUAL
    download_tracks(tracks, tmp_path, album="Lista", origen="https://open.spotify.com/playlist/x")
    m = leer_manifiesto(tmp_path)
    assert m["origen"] == "https://open.spotify.com/playlist/x" and m["nombre"] == "Lista"
    assert m["formato"] == "mp3"
    assert m["canciones"]["sp:id1"] == {
        "archivo": "01 - A - B.mp3", "youtube_url": tracks[0].youtube_url, "youtube_titulo": "",
        "titulo": "B", "artista": "A", "manual": False}
    assert m["canciones"]["sp:id2"]["manual"] is True


# ── Sincronización ──────────────────────────────────────────────────────────

def test_sincronizar_no_vuelve_a_descargar(tmp_path, descargas):
    tracks = [_t("B", "id1"), _t("C", "id2")]
    assert len(download_tracks(tracks, tmp_path).ok) == 2
    descargas.clear()
    r = download_tracks(tracks, tmp_path)
    assert not descargas and len(r.skipped) == 2 and not r.renamed and not r.removed


def test_reordenar_intercambia_numeros_sin_colision(tmp_path, descargas):
    b, c, d = _t("B", "id1"), _t("C", "id2"), _t("D", "id3")
    download_tracks([b, c, d], tmp_path)
    descargas.clear()
    logs = []
    r = download_tracks([c, b, d], tmp_path, on_log=logs.append)
    assert not descargas and len(r.skipped) == 3
    assert sorted(r.renamed) == [("01 - A - B.mp3", "02 - A - B.mp3"), ("02 - A - C.mp3", "01 - A - C.mp3")]
    assert any(l.startswith("Renumerada: ") for l in logs)
    assert _audio(tmp_path) == ["01 - A - C.mp3", "02 - A - B.mp3", "03 - A - D.mp3"]
    assert (tmp_path / "01 - A - C.mp3").read_bytes().endswith(c.youtube_url.encode())
    assert (tmp_path / "02 - A - B.mp3").read_bytes().endswith(b.youtube_url.encode())
    m = leer_manifiesto(tmp_path)
    assert m["canciones"]["sp:id1"]["archivo"] == "02 - A - B.mp3"
    assert not [p for p in tmp_path.iterdir() if "renombrando" in p.name]


def test_nueva_al_principio_renumera_y_solo_descarga_la_nueva(tmp_path, descargas):
    b, c = _t("B", "id1"), _t("C", "id2")
    download_tracks([b, c], tmp_path)
    descargas.clear()
    nueva = _t("N", "id9")
    r = download_tracks([nueva, b, c], tmp_path)
    assert descargas == [nueva.youtube_url] and [t.title for t in r.ok] == ["N"]
    assert _audio(tmp_path) == ["01 - A - N.mp3", "02 - A - B.mp3", "03 - A - C.mp3"]


def test_cambio_de_ancho_de_numero(tmp_path, descargas):
    tracks = [_t(f"T{i}", f"id{i}") for i in range(9)]
    download_tracks(tracks, tmp_path)
    descargas.clear()
    tracks.append(_t("Nueva", "idx"))
    tracks += [_t(f"U{i}", f"u{i}", url="") for i in range(95)]   # 105 canciones: 3 cifras
    r = download_tracks(tracks, tmp_path)
    assert descargas == [tracks[9].youtube_url] and len(r.renamed) == 9
    assert "001 - A - T0.mp3" in _audio(tmp_path)


def test_migracion_de_carpeta_sin_manifiesto(tmp_path, descargas):
    (tmp_path / "01 - A - B.mp3").write_bytes(b"b")
    (tmp_path / "02 - A - C.mp3").write_bytes(b"c")
    (tmp_path / "07 - Otro - Suelta.mp3").write_bytes(b"x")
    (tmp_path / "notas.txt").write_text("hola")
    r = download_tracks([_t("C", "id2"), _t("N", "id9"), _t("B", "id1")], tmp_path)
    assert [t.title for t in r.ok] == ["N"] and [t.title for t in r.skipped] == ["C", "B"]
    assert sorted(r.renamed) == [("01 - A - B.mp3", "03 - A - B.mp3"), ("02 - A - C.mp3", "01 - A - C.mp3")]
    assert (tmp_path / "03 - A - B.mp3").read_bytes().endswith(b"b")
    assert (tmp_path / "07 - Otro - Suelta.mp3").exists() and not r.removed
    m = leer_manifiesto(tmp_path)
    assert set(m["canciones"]) == {"sp:id1", "sp:id2", "sp:id9"}


def test_migracion_nombre_largo_recortado(tmp_path, descargas):
    t = _t("X" * 200, "id1")
    viejo = download.nombre_archivo(3, 5, t) + ".mp3"
    (tmp_path / viejo).write_bytes(b"")
    r = download_tracks([t], tmp_path)
    assert not descargas and len(r.skipped) == 1 and len(r.renamed) == 1


def test_quitadas_detectadas_y_movidas(tmp_path, descargas):
    b, c, d = _t("B", "id1"), _t("C", "id2"), _t("D", "id3")
    download_tracks([b, c, d], tmp_path)
    descargas.clear()
    r = download_tracks([b, d], tmp_path)
    assert not descargas and r.removed == ["02 - A - C.mp3"]
    assert r.renamed == [("03 - A - D.mp3", "02 - A - D.mp3")]
    assert (tmp_path / "02 - A - C.mp3").exists()   # sin mover_quitadas se queda
    assert "sp:id2" in leer_manifiesto(tmp_path)["canciones"]

    r = download_tracks([b, d], tmp_path, mover_quitadas=True)
    assert r.removed == ["02 - A - C.mp3"]
    assert (tmp_path / CARPETA_QUITADAS / "02 - A - C.mp3").read_bytes().endswith(c.youtube_url.encode())
    assert not (tmp_path / "02 - A - C.mp3").exists()
    assert "sp:id2" not in leer_manifiesto(tmp_path)["canciones"]
    assert not download_tracks([b, d], tmp_path).removed


def test_quitada_cuyo_numero_ocupa_otra(tmp_path, descargas):
    # C (02) se quita y D pasa a ser la 02: no colisionan porque el nombre incluye el título
    b, c, d = _t("B", "id1"), _t("C", "id2"), _t("D", "id3")
    download_tracks([b, c, d], tmp_path)
    r = download_tracks([b, d], tmp_path)
    assert _audio(tmp_path) == ["01 - A - B.mp3", "02 - A - C.mp3", "02 - A - D.mp3"]
    assert r.removed == ["02 - A - C.mp3"]


def test_cancion_repetida_en_la_lista(tmp_path, descargas):
    t = _t("B", "id1")
    r = download_tracks([t, Track(**{**t.__dict__, "candidates": []})], tmp_path)
    assert len(r.ok) == 2
    assert set(leer_manifiesto(tmp_path)["canciones"]) == {"sp:id1", "sp:id1#2"}
    assert len(download_tracks([t, t], tmp_path).skipped) == 2


def test_cancelar_conserva_lo_descargado_en_el_manifiesto(tmp_path, monkeypatch):
    cancel = threading.Event()

    def descargar(url, opts, _cancel):
        ruta = Path(opts["outtmpl"].replace("%%", "%").replace("%(ext)s", "mp3"))
        ruta.write_bytes(b"")
        cancel.set()
        return {"requested_downloads": [{"filepath": str(ruta)}]}

    monkeypatch.setattr(download, "_descargar_una", descargar)
    r = download_tracks([_t("B", "id1"), _t("C", "id2")], tmp_path, cancel=cancel, album="L")
    assert len(r.ok) == 1
    assert list(leer_manifiesto(tmp_path)["canciones"]) == ["sp:id1"]
    assert (tmp_path / "L.m3u8").read_text(encoding="utf-8").count("#EXTINF") == 1


def test_renumerar_actualiza_numero_de_pista(tmp_path, monkeypatch):
    from mutagen.id3 import ID3
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")

    def descargar(url, opts, cancel):
        ruta = Path(opts["outtmpl"].replace("%%", "%").replace("%(ext)s", "mp3"))
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "anullsrc=r=44100:cl=mono", "-t", "1", str(ruta)], check=True)
        return {"requested_downloads": [{"filepath": str(ruta)}]}

    monkeypatch.setattr(download, "_descargar_una", descargar)
    b, c = _t("B", "id1"), _t("C", "id2")
    download_tracks([b, c], tmp_path)
    download_tracks([c, b], tmp_path)
    assert str(ID3(tmp_path / "02 - A - B.mp3")["TRCK"]) == "2/2"
    assert str(ID3(tmp_path / "01 - A - C.mp3")["TRCK"]) == "1/2"


# ── Lista local .m3u8 ───────────────────────────────────────────────────────

def test_m3u8_rutas_relativas_y_orden(tmp_path, descargas):
    b, c = _t("B", "id1", dur=200), _t("C", "id2")
    download_tracks([b, c], tmp_path / "Mi lista", album="Mi lista")
    sin = _t("Sin", "id5", url="")
    download_tracks([sin, c, b], tmp_path / "Mi lista", album="Mi lista")
    texto = (tmp_path / "Mi lista" / "Mi lista.m3u8").read_text(encoding="utf-8")
    assert texto.splitlines() == [
        "#EXTM3U",
        "#EXTINF:-1,A - C", "02 - A - C.mp3",
        "#EXTINF:200,A - B", "03 - A - B.mp3",
    ]
    assert not download_tracks([b], tmp_path / "otra", lista_m3u=False).failed
    assert not list((tmp_path / "otra").glob("*.m3u8"))


# ── Reutilizar enlaces ──────────────────────────────────────────────────────

def test_aplicar_manifiesto():
    manifiesto = {"canciones": {
        "sp:id1": {"archivo": "01 - A - B.mp3", "youtube_url": "u1", "youtube_titulo": "Vídeo B",
                   "manual": False},
        "sp:id2": {"archivo": "02 - A - C.mp3", "youtube_url": "u2", "manual": True},
        "tx:a|d": {"archivo": "03 - A - D.mp3", "youtube_url": ""},
    }}
    tracks = [_t("B", "id1", url=""), _t("C", "id2", url=""), _t("D", url=""), _t("E", "id9", url="")]
    assert aplicar_manifiesto(tracks, manifiesto) == 2
    assert (tracks[0].youtube_url, tracks[0].youtube_title, tracks[0].status) == ("u1", "Vídeo B", Status.OK)
    assert (tracks[1].youtube_url, tracks[1].status) == ("u2", Status.MANUAL)
    assert not tracks[2].youtube_url and not tracks[3].youtube_url
    manual = _t("B", "id1", url="mia")
    manual.status = Status.MANUAL
    assert aplicar_manifiesto([manual], manifiesto) == 0 and manual.youtube_url == "mia"
    assert aplicar_manifiesto(tracks, {}) == 0


# ── Importar .csv ───────────────────────────────────────────────────────────

def test_importables():
    assert "csv" in IMPORTABLES


def test_from_csv_ida_y_vuelta(tmp_path):
    tracks = [
        Track("Uno", ["A", "B"], 223, "Disco", "id1", "https://youtu.be/1", "Vídeo 1", 0.91, Status.OK),
        Track("Dos", ["C"], None, "", "", "https://youtu.be/2", "", None, Status.MANUAL),
        Track("Tres", ["D"], 65, status=Status.FAILED),
        Track("Cuatro", [], 3723, status=Status.SEARCHING),
    ]
    ruta = tmp_path / "Mi lista.csv"
    to_csv(tracks, ruta)
    nombre, leidas = from_csv(ruta)
    assert nombre == "Mi lista"
    for a, b in zip(tracks[:3], leidas):
        assert (a.title, a.artists, a.duration_s, a.album, a.spotify_id, a.youtube_url,
                a.youtube_title, a.score, a.status) == \
               (b.title, b.artists, b.duration_s, b.album, b.spotify_id, b.youtube_url,
                b.youtube_title, b.score, b.status)
    assert leidas[3].status == Status.PENDING and leidas[3].duration_s == 3723


def test_from_csv_propio_estado_desconocido(tmp_path):
    ruta = tmp_path / "x.csv"
    ruta.write_text("titulo,artista,estado,youtube_url\nA,B,raro,https://youtu.be/x\nC,D,raro,\n",
                    encoding="utf-8")
    _, (con, sin) = from_csv(ruta)
    assert con.status == Status.MANUAL and sin.status == Status.PENDING


EXPORTIFY = ('"Track URI","Track Name","Artist URI(s)","Artist Name(s)","Album Name","Duration (ms)"\n'
             '"spotify:track:4uLU6hMCjMI75M1A2tKUQC","Never Gonna Give You Up","spotify:artist:x",'
             '"Rick Astley","Whenever You Need Somebody","213573"\n'
             '"spotify:track:6habFhsOp2NvshLv26DqMb","Despacito","spotify:artist:y,spotify:artist:z",'
             '"{artistas}","Vida","229360"\n'
             '"spotify:local:::Local:100","Local","","","","100000"\n')


@pytest.mark.parametrize("separador_artistas", [",", ";"])
def test_from_csv_exportify(tmp_path, separador_artistas):
    ruta = tmp_path / "Exportada.csv"
    texto = EXPORTIFY.replace("{artistas}", f"Luis Fonsi{separador_artistas}Daddy Yankee")
    ruta.write_text(texto, encoding="utf-8-sig")   # con BOM
    nombre, tracks = from_csv(ruta)
    assert nombre == "Exportada" and len(tracks) == 3
    rick, despacito, local = tracks
    assert (rick.title, rick.artists, rick.spotify_id, rick.duration_s, rick.album) == \
           ("Never Gonna Give You Up", ["Rick Astley"], "4uLU6hMCjMI75M1A2tKUQC", 214,
            "Whenever You Need Somebody")
    assert despacito.artists == ["Luis Fonsi", "Daddy Yankee"]
    assert rick.status == Status.PENDING and not rick.youtube_url
    assert local.spotify_id == "" and local.artists == []


def test_from_csv_exportify_punto_y_coma(tmp_path):
    ruta = tmp_path / "excel.csv"
    ruta.write_bytes("﻿Track Name;Artist Name(s);Album Name;Duration (ms);Track URI\r\n"
                     "Canción, con coma;Artista;Álbum;1000;spotify:track:abc\r\n".encode("utf-8"))
    _, (t,) = from_csv(ruta)
    assert (t.title, t.artists, t.album, t.duration_s, t.spotify_id) == \
           ("Canción, con coma", ["Artista"], "Álbum", 1, "abc")


def test_from_csv_cabeceras_desconocidas(tmp_path):
    ruta = tmp_path / "otro.csv"
    ruta.write_text("nombre,cantante\nA,B\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columnas"):
        from_csv(ruta)


# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_sync_sin_manifiesto(tmp_path, capsys):
    from spotyurl.cli import main
    assert main(["--sync", str(tmp_path)]) == 1
    assert "no tiene manifiesto" in capsys.readouterr().out


def test_cli_sync_sin_origen(tmp_path, capsys):
    from spotyurl.cli import main
    guardar_manifiesto(tmp_path, {"origen": "", "canciones": {}})
    assert main(["--sync", str(tmp_path)]) == 1
    assert "enlace de Spotify" in capsys.readouterr().out


def test_cli_csv_descarga_sin_buscar(tmp_path, monkeypatch, capsys, descargas):
    from spotyurl import cli

    class SinBusqueda:
        def __init__(self, *a, **k):
            pass

        def match(self, track, use_cache=True):
            raise AssertionError("no debería buscar")

        def save_cache(self):
            pass

    monkeypatch.setattr(cli, "YouTubeMatcher", SinBusqueda)
    csv_ruta = tmp_path / "Lista.csv"
    to_csv([_t("B", "id1"), _t("C", "id2")], csv_ruta)
    audio = tmp_path / "audio"
    assert cli.main(["--csv", str(csv_ruta), "--download", "--no-clipboard",
                     "-o", str(tmp_path / "enlaces"), "--audio-dir", str(audio)]) == 0
    assert _audio(audio / "Lista") == ["01 - A - B.mp3", "02 - A - C.mp3"]

    # --sync de esa carpeta con el .csv reordenado: no descarga, renumera
    descargas.clear()
    to_csv([_t("C", "id2"), _t("B", "id1")], csv_ruta)
    assert cli.main(["--sync", str(audio / "Lista"), "--csv", str(csv_ruta), "--no-clipboard",
                     "-o", str(tmp_path / "enlaces")]) == 0
    salida = capsys.readouterr().out
    assert not descargas and "Renumeradas    : 2" in salida
    assert _audio(audio / "Lista") == ["01 - A - C.mp3", "02 - A - B.mp3"]
    json.loads((audio / "Lista" / ARCHIVO_MANIFIESTO).read_text(encoding="utf-8"))
