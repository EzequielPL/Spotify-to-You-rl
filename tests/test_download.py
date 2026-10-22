"""Descarga de audio (sin red: YoutubeDL se sustituye por clases falsas)."""

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

    def download(self, urls):
        raise RuntimeError("ERROR: [youtube] x: Video unavailable\nmás detalles")


class YDLOk(YDLFalla):
    instancias = []

    def __init__(self, opts):
        super().__init__(opts)
        YDLOk.instancias.append(self)

    def download(self, urls):
        for hook in self.opts["progress_hooks"]:
            hook({"status": "downloading"})


@pytest.fixture(autouse=True)
def sin_ffmpeg(monkeypatch):
    monkeypatch.setattr(download, "ffmpeg_disponible", lambda: False)


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
        def download(self, urls):
            cancel.set()
            super().download(urls)

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
    monkeypatch.setattr(download, "ffmpeg_disponible", lambda: True)
    monkeypatch.setattr(download, "ffmpeg_path", lambda: "/bin/ffmpeg")
    llamadas = []
    monkeypatch.setattr(download, "_descargar_una", lambda url, opts, cancel: llamadas.append(opts))
    t = Track("B", ["A"], youtube_url="https://youtu.be/aaaaaaaaaaa")
    assert len(download.download_tracks([t], tmp_path, formato="m4a").skipped) == 1
    r = download.download_tracks([t], tmp_path, formato="mp3")
    assert len(r.ok) == 1 and llamadas[0]["postprocessors"][0]["preferredcodec"] == "mp3"
