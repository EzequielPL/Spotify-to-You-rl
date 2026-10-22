"""Descarga de audio (sin red: YoutubeDL se sustituye por clases falsas)."""

import json
import subprocess
import threading

import pytest

from spotyurl import download
from spotyurl.download import download_tracks, nombre_archivo
from spotyurl.models import Track


def _t(title, artist="A", url="https://www.youtube.com/watch?v=x"):
    return Track(title=title, artists=[artist] if artist else [], youtube_url=url)


class YDLProhibido:
    def __init__(self, *a, **k):
        raise AssertionError("no debería instanciarse YoutubeDL")


class YDLFalla:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        raise RuntimeError("ERROR: [youtube] x: Video unavailable\nmás detalles")


class YDLOk(YDLFalla):
    instancias = []

    def __init__(self, opts):
        super().__init__(opts)
        YDLOk.instancias.append(self)

    def extract_info(self, url, download=True):
        for hook in self.opts["progress_hooks"]:
            hook({"status": "downloading"})
        return {}


@pytest.fixture(autouse=True)
def sin_ffmpeg(monkeypatch):
    monkeypatch.setattr(download, "ffmpeg_path", lambda: None)


def test_nombre_archivo_padding():
    assert nombre_archivo(1, 5, _t("B")) == "01 - A - B"
    assert nombre_archivo(7, 120, _t("B")) == "007 - A - B"
    assert nombre_archivo(3, 9, _t("Solo", artist="")) == "03 - Solo"


def test_nombre_archivo_saneado():
    assert nombre_archivo(1, 3, _t("Back in Black?", artist="AC/DC")) == "01 - AC-DC - Back in Black"


def test_salta_existentes(tmp_path, monkeypatch):
    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLProhibido)
    (tmp_path / "01 - A - B.mp3").write_bytes(b"")
    progreso = []
    res = download_tracks([_t("B")], tmp_path, on_progress=lambda k, n: progreso.append((k, n)))
    assert [t.title for t in res.skipped] == ["B"]
    assert not res.ok and not res.failed
    assert progreso == [(1, 1)]


def test_part_no_cuenta_como_existente(tmp_path, monkeypatch):
    YDLOk.instancias = []
    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLOk)
    (tmp_path / "01 - A - B.m4a.part").write_bytes(b"")
    res = download_tracks([_t("B")], tmp_path)
    assert len(res.ok) == 1 and len(YDLOk.instancias) == 1


def test_ignora_sin_enlace_y_posicion_estable(tmp_path, monkeypatch):
    YDLOk.instancias = []
    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLOk)
    tracks = [_t("Sin", url=""), _t("Con 50%")]
    progreso = []
    res = download_tracks(tracks, tmp_path / "sub", on_progress=lambda k, n: progreso.append((k, n)))
    assert [t.title for t in res.ok] == ["Con 50%"]
    assert progreso == [(1, 1)]
    outtmpl = YDLOk.instancias[0].opts["outtmpl"]
    assert outtmpl.endswith("02 - A - Con 50%%.%(ext)s")
    assert (tmp_path / "sub").is_dir()


def test_fallo_va_a_failed_y_sigue(tmp_path, monkeypatch):
    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLFalla)
    logs = []
    res = download_tracks([_t("B"), _t("C")], tmp_path, on_log=logs.append)
    assert [(t.title, m) for t, m in res.failed] == [
        ("B", "[youtube] x: Video unavailable"),
        ("C", "[youtube] x: Video unavailable"),
    ]
    assert any("ffmpeg" in l for l in logs)


def test_cancelacion_devuelve_lo_hecho(tmp_path, monkeypatch):
    cancel = threading.Event()

    class YDLCancela(YDLOk):
        def extract_info(self, url, download=True):
            cancel.set()
            return super().extract_info(url, download)

    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLCancela)
    (tmp_path / "01 - A - B.mp3").write_bytes(b"")
    res = download_tracks([_t("B"), _t("C"), _t("D")], tmp_path, cancel=cancel)
    assert [t.title for t in res.skipped] == ["B"]
    assert not res.ok and not res.failed


def test_pista_error():
    from spotyurl.download import pista_error
    assert "yt-dlp" in pista_error("unable to download video data: HTTP Error 403: Forbidden")
    assert "ffmpeg" in pista_error("ffprobe and ffmpeg not found")
    assert pista_error("Video unavailable") and not pista_error("disco lleno")


def test_formato_no_soportado(tmp_path):
    with pytest.raises(ValueError):
        download.download_tracks([Track("B", ["A"], youtube_url="https://youtu.be/aaaaaaaaaaa")], tmp_path, formato="wav")


def test_opciones_segun_formato(tmp_path):
    hook = lambda _d: None
    sin = download._opciones(tmp_path, "x", None, "mp3", hook)
    assert "postprocessors" not in sin and "ffmpeg_location" not in sin
    con = download._opciones(tmp_path, "x", "/bin/ffmpeg", "m4a", hook)
    assert con["ffmpeg_location"] == "/bin/ffmpeg"
    assert con["postprocessors"][0]["preferredcodec"] == "m4a"


def test_cambiar_de_formato_vuelve_a_descargar(tmp_path, monkeypatch):
    # Con ffmpeg, un .m4a existente no cuenta si ahora se pide .mp3
    (tmp_path / "01 - A - B.m4a").write_bytes(b"")
    monkeypatch.setattr(download, "ffmpeg_path", lambda: "/bin/ffmpeg")
    llamadas = []
    monkeypatch.setattr(download, "_descargar_una", lambda url, opts, cancel: llamadas.append(opts))
    t = Track("B", ["A"], youtube_url="https://youtu.be/aaaaaaaaaaa")
    assert len(download.download_tracks([t], tmp_path, formato="m4a").skipped) == 1
    r = download.download_tracks([t], tmp_path, formato="mp3")
    assert len(r.ok) == 1 and llamadas[0]["postprocessors"][0]["preferredcodec"] == "mp3"


# ── Estados por canción (on_track) ──────────────────────────────────────────

class YDLProgreso(YDLOk):
    def extract_info(self, url, download=True):
        hook = self.opts["progress_hooks"][0]
        for hecho in (0, 50, 100):
            hook({"status": "downloading", "downloaded_bytes": hecho, "total_bytes_estimate": 100})
        hook({"status": "finished"})
        return {}


def test_on_track_secuencia_de_estados(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "INTERVALO_PROGRESO", 0)
    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLProgreso)
    (tmp_path / "02 - A - Ya.mp3").write_bytes(b"")
    tracks = [_t("Sin", url=""), _t("Ya"), _t("Nueva")]
    eventos = []
    download_tracks(tracks, tmp_path, on_track=lambda i, e, p: eventos.append((i, e, round(p))))
    assert all(e in download.ESTADOS_AUDIO for _, e, _ in eventos)
    assert eventos == [
        (1, "cola", 0), (2, "cola", 0),
        (1, "existe", 100),
        (2, "descargando", 0), (2, "descargando", 0), (2, "descargando", 50), (2, "descargando", 100),
        (2, "etiquetando", 100), (2, "ok", 100),
    ]


def test_on_track_convirtiendo_y_error(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "ffmpeg_path", lambda: "/bin/ffmpeg")
    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLProgreso)
    eventos = []
    download_tracks([_t("B")], tmp_path, on_track=lambda i, e, p: eventos.append(e))
    assert eventos[-3:] == ["convirtiendo", "etiquetando", "ok"]

    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLFalla)
    eventos.clear()
    download_tracks([_t("C")], tmp_path, on_track=lambda i, e, p: eventos.append(e))
    assert eventos == ["cola", "descargando", "error"]


def test_on_track_cancelada_vuelve_a_cola(tmp_path, monkeypatch):
    cancel = threading.Event()

    class YDLCancela(YDLOk):
        def extract_info(self, url, download=True):
            cancel.set()
            return super().extract_info(url, download)

    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLCancela)
    eventos = []
    download_tracks([_t("B"), _t("C")], tmp_path, cancel=cancel,
                    on_track=lambda i, e, p: eventos.append((i, e)))
    assert eventos == [(0, "cola"), (1, "cola"), (0, "descargando"), (0, "cola")]


# ── Etiquetas y carátula ────────────────────────────────────────────────────

def _ffmpeg_real():
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def _silencio(ruta):
    subprocess.run([_ffmpeg_real(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=mono", "-t", "1", str(ruta)], check=True)
    return ruta


def _jpg(ruta, tam):
    subprocess.run([_ffmpeg_real(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"color=c=red:s={tam}", "-frames:v", "1", str(ruta)], check=True)
    return ruta.read_bytes()


PORTADA = b"\xff\xd8\xff\xe0" + b"0" * 100


def test_etiquetar_mp3(tmp_path):
    from mutagen.id3 import ID3
    ruta = _silencio(tmp_path / "x.mp3")
    t = Track("Título", ["A", "B"], album="Disco")
    assert download.etiquetar(ruta, t, "Mi playlist", 3, 12, PORTADA)
    tags = ID3(ruta)
    assert tags.version[:2] == (2, 3)
    assert str(tags["TIT2"]) == "Título" and str(tags["TPE1"]) == "A, B"
    assert str(tags["TALB"]) == "Disco" and str(tags["TPE2"]) == "A"
    assert str(tags["TRCK"]) == "3/12"
    apic = tags.getall("APIC")[0]
    assert apic.data == PORTADA and apic.mime == "image/jpeg" and apic.type == 3


def test_etiquetar_m4a_album_de_la_playlist(tmp_path):
    from mutagen.mp4 import MP4, MP4Cover
    ruta = _silencio(tmp_path / "x.m4a")
    assert download.etiquetar(ruta, Track("T", ["A"]), "Mi playlist", 1, 2, PORTADA)
    tags = MP4(ruta).tags
    assert tags["\xa9nam"] == ["T"] and tags["\xa9ART"] == ["A"]
    assert tags["\xa9alb"] == ["Mi playlist"] and tags["aART"] == [download.ARTISTA_VARIOS]
    assert tags["trkn"] == [(1, 2)]
    assert bytes(tags["covr"][0]) == PORTADA and tags["covr"][0].imageformat == MP4Cover.FORMAT_JPEG


def test_etiquetar_otros_formatos_no_hace_nada(tmp_path):
    ruta = tmp_path / "x.webm"
    ruta.write_bytes(b"no es audio")
    assert download.etiquetar(ruta, _t("B"), "", 1, 1) is False


def _ydl_que_crea(crear):
    """YoutubeDL falso que crea el archivo final como lo haría la conversión."""
    class YDLCrea(YDLOk):
        def extract_info(self, url, download=True):
            ruta = self.opts["outtmpl"].replace("%%", "%").replace("%(ext)s", "mp3")
            crear(ruta)
            return {"thumbnail": "https://i.ytimg.com/vi/x/maxresdefault.jpg",
                    "requested_downloads": [{"filepath": ruta}]}
    return YDLCrea


def test_descarga_etiqueta_con_portada_de_spotify_cacheada(tmp_path, monkeypatch):
    from mutagen.id3 import ID3
    monkeypatch.setattr(download, "ffmpeg_path", _ffmpeg_real)
    monkeypatch.setattr("yt_dlp.YoutubeDL", _ydl_que_crea(_silencio))
    pedidas = []

    def leer(url):
        pedidas.append(url)
        if "oembed" in url:
            return json.dumps({"thumbnail_url": "https://i.scdn.co/image/abc"}).encode()
        return PORTADA

    monkeypatch.setattr(download, "_leer_url", leer)
    tracks = [Track("B", ["A"], spotify_id="id1", youtube_url="u"),
              Track("C", ["A"], spotify_id="id2", youtube_url="u")]
    res = download_tracks(tracks, tmp_path, album="Lista")
    assert len(res.ok) == 2
    assert pedidas.count("https://i.scdn.co/image/abc") == 1   # la imagen se cachea por URL
    assert pedidas[0].endswith("/track/id1")
    tags = ID3(tmp_path / "02 - A - C.mp3")
    assert str(tags["TALB"]) == "Lista" and str(tags["TRCK"]) == "2/2"
    assert tags.getall("APIC")[0].data == PORTADA


def test_portada_de_youtube_recortada(tmp_path, monkeypatch):
    from mutagen.id3 import ID3
    ffmpeg = _ffmpeg_real()
    monkeypatch.setattr(download, "ffmpeg_path", lambda: ffmpeg)
    monkeypatch.setattr("yt_dlp.YoutubeDL", _ydl_que_crea(_silencio))
    miniatura = _jpg(tmp_path / "mini.jpg", "64x36")

    def leer(url):
        if "oembed" in url:
            raise OSError("sin red")
        return miniatura

    monkeypatch.setattr(download, "_leer_url", leer)
    res = download_tracks([Track("B", ["A"], spotify_id="id1", youtube_url="u")], tmp_path / "out")
    assert len(res.ok) == 1
    datos = ID3(tmp_path / "out" / "01 - A - B.mp3").getall("APIC")[0].data
    (tmp_path / "portada.jpg").write_bytes(datos)
    info = subprocess.run([ffmpeg, "-i", str(tmp_path / "portada.jpg")],
                          capture_output=True).stderr.decode(errors="replace")
    assert "36x36" in info


def test_fallo_de_portada_y_etiquetas_no_rompe(tmp_path, monkeypatch):
    def sin_red(url):
        raise OSError("sin red")

    def basura(ruta):
        with open(ruta, "wb") as f:
            f.write(b"esto no es un mp3")

    monkeypatch.setattr(download, "_leer_url", sin_red)
    monkeypatch.setattr("yt_dlp.YoutubeDL", _ydl_que_crea(basura))
    logs = []
    res = download_tracks([Track("B", ["A"], spotify_id="id", youtube_url="u")], tmp_path, on_log=logs.append)
    assert len(res.ok) == 1 and not res.failed
    assert any("Carátula no disponible" in l for l in logs)


def test_archivo_final_por_respaldo(tmp_path):
    (tmp_path / "01 - A - [B].m4a").write_bytes(b"")
    (tmp_path / "01 - A - [B].mp3").write_bytes(b"")
    assert download._archivo_final(None, tmp_path, "01 - A - [B]", "mp3").name == "01 - A - [B].mp3"
    assert download._archivo_final({}, tmp_path, "nada", "mp3") is None
