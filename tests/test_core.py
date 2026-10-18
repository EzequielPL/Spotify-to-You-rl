"""Tests sin red del núcleo de spotify: parseo de entradas, puntuación y exportación."""

from spotyurl.export import to_csv, to_m3u, to_txt
from spotyurl.models import Status, Track, fmt_duration, parse_duration
from spotyurl.spotify import parse_source, parse_text_list
from spotyurl.youtube import UMBRAL_OK, Candidate, puntuar


# ── parse_source ─────────────────────────────────────────────────────────────

def test_parse_playlist_con_idioma_y_query():
    src = parse_source("https://open.spotify.com/intl-es/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc")
    assert (src.kind, src.id) == ("playlist", "37i9dQZF1DXcBWIGoYBM5M")
    assert src.url == "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


def test_parse_album_y_uri():
    assert parse_source("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy").kind == "album"
    assert parse_source("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M").id == "37i9dQZF1DXcBWIGoYBM5M"


def test_parse_no_reconocido():
    assert parse_source("https://open.spotify.com/track/292kifgxa7S78AuzA5NMpL") is None
    assert parse_source("hola") is None


# ── parse_text_list ──────────────────────────────────────────────────────────

def test_lista_de_texto():
    tracks = parse_text_list("1. Bruno Mars - Locked Out of Heaven\n\n- Rosalía - Despechá\nSolo un título\n")
    assert [(t.artist, t.title) for t in tracks] == [
        ("Bruno Mars", "Locked Out of Heaven"),
        ("Rosalía", "Despechá"),
        ("", "Solo un título"),
    ]


def test_lista_conserva_guiones_del_titulo():
    (t,) = parse_text_list("Jay-Z - Run This Town - Remastered")
    assert t.artist == "Jay-Z" and t.title == "Run This Town - Remastered"


# ── duraciones ───────────────────────────────────────────────────────────────

def test_duraciones():
    assert parse_duration("3:43") == 223
    assert parse_duration("1:02:03") == 3723
    assert parse_duration("hace 2 días") is None
    assert fmt_duration(223) == "3:43" and fmt_duration(None) == ""


# ── puntuación ───────────────────────────────────────────────────────────────

TRACK = Track("Patient Zero", ["Taylor Swift"], duration_s=225)


def test_audio_oficial_gana():
    oficial = Candidate("a" * 11, "Taylor Swift - Patient Zero (Official Lyric Video)", "Taylor Swift", 226)
    piano = Candidate("b" * 11, "Patient Zero (Piano Version)", "Random Covers", 225)
    video_largo = Candidate("c" * 11, "Taylor Swift - Patient Zero (Official Music Video)", "Taylor Swift", 313)
    s_of, s_pi, s_vl = (puntuar(TRACK, c) for c in (oficial, piano, video_largo))
    assert s_of >= UMBRAL_OK
    assert s_of > s_pi and s_of > s_vl


def test_canal_topic_y_penalizacion_live():
    topic = Candidate("a" * 11, "Patient Zero", "Taylor Swift - Topic", 225)
    live = Candidate("b" * 11, "Taylor Swift - Patient Zero (Live)", "Taylor Swift", 230)
    assert puntuar(TRACK, topic) > puntuar(TRACK, live)


def test_live_no_penaliza_si_el_original_es_live():
    t = Track("Patient Zero (Live)", ["Taylor Swift"], duration_s=230)
    live = Candidate("b" * 11, "Taylor Swift - Patient Zero (Live)", "Taylor Swift", 230)
    assert puntuar(t, live) >= UMBRAL_OK


# ── exportación ──────────────────────────────────────────────────────────────

def _tracks():
    return [
        Track("A", ["X"], 200, youtube_url="https://www.youtube.com/watch?v=aaaaaaaaaaa", status=Status.OK),
        Track("B", ["Y"], status=Status.FAILED),
    ]


def test_export_txt(tmp_path):
    p = tmp_path / "out.txt"
    assert to_txt(_tracks(), p) == 1
    assert p.read_text(encoding="utf-8") == "https://www.youtube.com/watch?v=aaaaaaaaaaa\n"


def test_export_csv_y_m3u(tmp_path):
    assert to_csv(_tracks(), tmp_path / "o.csv") == 2
    assert "sin match" in (tmp_path / "o.csv").read_text(encoding="utf-8-sig")
    assert to_m3u(_tracks(), tmp_path / "o.m3u") == 1
    assert "#EXTINF:200,X - A" in (tmp_path / "o.m3u").read_text(encoding="utf-8")
