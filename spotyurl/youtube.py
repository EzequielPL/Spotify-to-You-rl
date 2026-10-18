"""
Búsqueda en YouTube con yt-dlp y elección del mejor candidato.

Cada canción pide varios resultados (extract_flat, sin descargar nada) y los
puntúa por coincidencia de título/artista, diferencia de duración con Spotify,
canal oficial y palabras que suelen indicar otra versión (cover, live…).
"""

import json
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .models import Status, Track

UMBRAL_OK = 0.6

# Palabras que delatan otra versión, salvo que aparezcan en el título original
PALABRAS_SOSPECHOSAS = [
    "cover", "live", "en vivo", "karaoke", "instrumental", "remix", "sped up",
    "slowed", "reverb", "8d", "nightcore", "acoustic", "acustico", "piano",
    "unplugged", "orchestral", "demo", "tutorial", "reaction", "1 hour", "1 hora",
]
# Suelen ser la canción correcta, pero se prefiere el audio oficial
PALABRAS_LEVES = ["lyrics", "lyric", "letra", "visualizer"]


@dataclass
class Candidate:
    id: str
    title: str
    channel: str
    duration_s: int | None
    score: float = 0.0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _tokens(texto: str) -> set[str]:
    return set(normalizar(texto).split())


def _cobertura(buscado: str, en: str) -> float:
    """Fracción de palabras de `buscado` presentes en `en`."""
    tb = _tokens(buscado)
    return len(tb & _tokens(en)) / len(tb) if tb else 0.0


def _titulo_base(titulo: str) -> str:
    """Quita '(feat. X)', '- Remastered 2011', etc. del título de Spotify."""
    titulo = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", titulo)
    return re.split(r"\s+-\s+", titulo)[0].strip() or titulo


def puntuar(track: Track, cand: Candidate) -> float:
    titulo_yt = cand.title
    contexto = f"{cand.title} {cand.channel}"
    score = 0.45 * _cobertura(_titulo_base(track.title), titulo_yt)
    if track.artists:
        score += 0.25 * _cobertura(track.artists[0], contexto)
    else:
        score += 0.1

    if track.duration_s and cand.duration_s:
        diff = abs(track.duration_s - cand.duration_s)
        score += 0.3 if diff <= 3 else 0.2 if diff <= 7 else 0.05 if diff <= 15 else -0.15 if diff <= 40 else -0.4
    else:
        score += 0.1

    canal = cand.channel.lower()
    if canal.endswith(" - topic") or "vevo" in canal:
        score += 0.1
    elif track.artists and normalizar(track.artists[0]) in normalizar(canal):
        score += 0.1   # canal del propio artista
    if "official" in normalizar(titulo_yt) or "oficial" in normalizar(titulo_yt):
        score += 0.05

    original = normalizar(f"{track.title} {track.album}")
    norm_yt = f" {normalizar(titulo_yt)} "
    for palabra in PALABRAS_SOSPECHOSAS:
        if f" {palabra} " in norm_yt and palabra not in original:
            score -= 0.35
    for palabra in PALABRAS_LEVES:
        if f" {palabra} " in norm_yt and palabra not in original:
            score -= 0.05
            break
    return round(score, 3)


class YouTubeMatcher:
    """
    Reutiliza una única instancia de YoutubeDL. No es thread-safe:
    úsalo desde un solo hilo de trabajo.
    """

    def __init__(
        self,
        n_results: int = 6,
        query_template: str = "{artist} - {title}",
        cache_path: Path | None = None,
    ):
        from yt_dlp import YoutubeDL

        self.n_results = n_results
        self.query_template = query_template
        self.cache_path = cache_path
        self._cache: dict[str, dict] = {}
        if cache_path and cache_path.exists():
            try:
                self._cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache = {}
        self._ydl = YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "noplaylist": True,
        })

    def _query(self, track: Track) -> str:
        return self.query_template.format(
            artist=track.artists[0] if track.artists else "",
            title=track.title,
            album=track.album,
        ).strip(" -")

    def _cache_key(self, track: Track) -> str:
        return f"{normalizar(track.artist)}|{normalizar(track.title)}|{track.duration_s or ''}"

    def candidates(self, track: Track, cancel: threading.Event | None = None) -> list[Candidate]:
        """Busca en YouTube y devuelve candidatos ordenados de mejor a peor."""
        cands = self._buscar(self._query(track), cancel)
        if not cands:
            # Segunda oportunidad con una consulta más simple
            cands = self._buscar(f"{track.title} {track.artist}", cancel)
        for c in cands:
            c.score = puntuar(track, c)
        return sorted(cands, key=lambda c: c.score, reverse=True)

    def _buscar(self, texto: str, cancel: threading.Event | None) -> list[Candidate]:
        from yt_dlp.utils import DownloadError

        query = f"ytsearch{self.n_results}:{texto}"
        for intento, espera in enumerate((0, 5, 15, 45)):
            if espera:
                if cancel and cancel.wait(espera):
                    return []
                if not cancel:
                    time.sleep(espera)
            try:
                result = self._ydl.extract_info(query, download=False)
                break
            except DownloadError as e:
                # 429 / "confirm you're not a bot": reintentar con espera creciente
                if intento == 3 or not re.search(r"429|too many|not a bot", str(e), re.I):
                    raise
        entries = [e for e in (result or {}).get("entries") or [] if e and e.get("id")]
        return [
            Candidate(
                id=e["id"],
                title=e.get("title") or "",
                channel=e.get("channel") or e.get("uploader") or "",
                duration_s=int(e["duration"]) if e.get("duration") else None,
            )
            for e in entries
        ]

    def match(self, track: Track, cancel: threading.Event | None = None, use_cache: bool = True) -> Track:
        """Rellena youtube_url/youtube_title/score/status del track y lo devuelve."""
        key = self._cache_key(track)
        hit = self._cache.get(key) if use_cache else None
        if hit:
            track.youtube_url, track.youtube_title, track.score = hit["url"], hit["title"], hit["score"]
        else:
            cands = self.candidates(track, cancel)
            if not cands:
                track.youtube_url, track.youtube_title, track.score = "", "", None
                track.status = Status.FAILED
                return track
            best = cands[0]
            track.youtube_url, track.youtube_title, track.score = best.url, best.title, best.score
            self._cache[key] = {"url": best.url, "title": best.title, "score": best.score}
        track.status = Status.OK if track.score >= UMBRAL_OK else Status.DOUBTFUL
        return track

    def save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
