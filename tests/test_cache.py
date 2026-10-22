"""Caché de búsquedas: candidatos y elecciones manuales (sin red)."""

import json

import pytest

from spotyurl import youtube
from spotyurl.models import Status, Track
from spotyurl.youtube import YouTubeMatcher, cache_key, recordar_eleccion

RESULTADOS = {
    "entries": [
        {"id": "aaaaaaaaaaa", "title": "Artista - Canción (Official Audio)", "channel": "Artista", "duration": 200},
        {"id": "bbbbbbbbbbb", "title": "Artista - Canción (Live)", "channel": "Otro", "duration": 260},
        {"id": "ccccccccccc", "title": "Canción karaoke", "channel": "Karaoke", "duration": 200},
    ]
}


class YDLBusqueda:
    busquedas = 0

    def __init__(self, opts):
        self.opts = opts

    def extract_info(self, query, download=False):
        YDLBusqueda.busquedas += 1
        return RESULTADOS


@pytest.fixture(autouse=True)
def ydl_falso(monkeypatch):
    YDLBusqueda.busquedas = 0
    monkeypatch.setattr("yt_dlp.YoutubeDL", YDLBusqueda)


def _track():
    return Track("Canción", ["Artista"], duration_s=200)


def test_candidatos_ida_y_vuelta_por_cache(tmp_path):
    cache = tmp_path / "cache.json"
    m = YouTubeMatcher(n_results=2, cache_path=cache)
    t = m.match(_track())
    assert t.status == Status.OK and t.youtube_url.endswith("aaaaaaaaaaa")
    assert [c.id for c in t.candidates] == ["aaaaaaaaaaa", "ccccccccccc", "bbbbbbbbbbb"]
    m.save_cache()

    guardado = json.loads(cache.read_text(encoding="utf-8"))[cache_key(t)]
    assert len(guardado["cands"]) == 2   # máximo n_results
    assert set(guardado["cands"][0]) == {"id", "title", "channel", "duration_s", "score"}

    t2 = YouTubeMatcher(n_results=2, cache_path=cache).match(_track())
    assert YDLBusqueda.busquedas == 1   # la segunda vino de la caché
    assert [c.id for c in t2.candidates] == ["aaaaaaaaaaa", "ccccccccccc"]
    assert t2.candidates[0].duration_s == 200 and t2.candidates[0].url == t.youtube_url
    assert (t2.youtube_url, t2.score, t2.status) == (t.youtube_url, t.score, Status.OK)


def test_cache_antigua_sin_candidatos(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({cache_key(_track()): {"url": "u", "title": "x", "score": 0.9}}), encoding="utf-8")
    t = YouTubeMatcher(cache_path=cache).match(_track())
    assert t.youtube_url == "u" and t.candidates == [] and t.status == Status.OK


def test_recordar_eleccion_y_match_manual(tmp_path):
    cache = tmp_path / "cache.json"
    m = YouTubeMatcher(cache_path=cache)
    t = m.match(_track())
    m.save_cache()

    t.youtube_url, t.youtube_title = "https://www.youtube.com/watch?v=bbbbbbbbbbb", "Elegida a mano"
    recordar_eleccion(cache, t)

    t2 = YouTubeMatcher(cache_path=cache).match(_track())
    assert t2.status == Status.MANUAL
    assert (t2.youtube_url, t2.youtube_title) == (t.youtube_url, "Elegida a mano")
    assert len(t2.candidates) == 3   # se conservan los candidatos previos
    assert YDLBusqueda.busquedas == 1

    # use_cache=False vuelve a buscar e ignora la elección manual
    t3 = YouTubeMatcher(cache_path=cache).match(_track(), use_cache=False)
    assert t3.status == Status.OK and t3.youtube_url.endswith("aaaaaaaaaaa")


def test_recordar_eleccion_sin_cache_previa_y_quitarla(tmp_path):
    cache = tmp_path / "no" / "existe.json"
    t = Track("Otra", ["B"], youtube_url="https://youtu.be/x", youtube_title="X")
    recordar_eleccion(cache, t)
    assert YouTubeMatcher(cache_path=cache).match(Track("Otra", ["B"])).status == Status.MANUAL
    assert YDLBusqueda.busquedas == 0

    t.youtube_url = ""
    recordar_eleccion(cache, t)
    assert "manual" not in json.loads(cache.read_text(encoding="utf-8"))[cache_key(t)]
    # Sin marca manual ni puntuación, la entrada no vale: se busca de nuevo
    YouTubeMatcher(cache_path=cache).match(Track("Otra", ["B"]))
    assert YDLBusqueda.busquedas == 1


def test_recordar_eleccion_tolera_json_roto(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text("{roto", encoding="utf-8")
    recordar_eleccion(cache, Track("A", youtube_url="https://youtu.be/x"))
    assert json.loads(cache.read_text(encoding="utf-8"))[cache_key(Track("A"))]["manual"] is True


def test_save_cache_no_pisa_eleccion_manual_posterior(tmp_path):
    cache = tmp_path / "cache.json"
    m = YouTubeMatcher(cache_path=cache)
    t = m.match(_track())
    t.youtube_url = "https://youtu.be/manual"
    recordar_eleccion(cache, t)   # mientras el buscador sigue abierto
    m.save_cache()
    assert json.loads(cache.read_text(encoding="utf-8"))[cache_key(t)]["url"] == "https://youtu.be/manual"


def test_recordar_eleccion_no_usa_yt_dlp(tmp_path, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("no debería instanciarse YoutubeDL")
    monkeypatch.setattr("yt_dlp.YoutubeDL", prohibido)
    recordar_eleccion(tmp_path / "c.json", Track("A", youtube_url="https://youtu.be/x"))
    assert youtube.cache_key(Track("A")) in json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
