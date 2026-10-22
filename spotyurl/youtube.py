"""
Búsqueda en YouTube con yt-dlp y elección del mejor candidato.

Cada canción pide varios resultados (extract_flat, sin descargar nada) y los
puntúa por coincidencia de título/artista, diferencia de duración con Spotify,
canal oficial y palabras que suelen indicar otra versión (cover, live…).

La caché (JSON) guarda por canción el enlace elegido, su puntuación, los
candidatos ("cands") y, si el usuario eligió otro vídeo a mano, "manual": True.
"""


import json
import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
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


def cache_key(track: Track) -> str:
    """Clave de la canción en la caché de búsquedas."""
    return f"{normalizar(track.artist)}|{normalizar(track.title)}|{track.duration_s or ''}"


def _cands_a_json(cands: list[Candidate], n: int | None = None) -> list[dict]:
    return [asdict(c) for c in cands[:n]]


def _cands_de_json(datos) -> list[Candidate]:
    """Reconstruye los candidatos guardados en la caché (ignora entradas rotas)."""
    cands = []
    for d in datos or []:
        try:
            cands.append(Candidate(
                id=d["id"], title=d.get("title") or "", channel=d.get("channel") or "",
                duration_s=d.get("duration_s"), score=d.get("score") or 0.0,
            ))
        except (KeyError, TypeError):
            continue
    return cands


def _leer_cache(cache_path: Path | None) -> dict[str, dict]:
    if not cache_path or not cache_path.exists():
        return {}
    try:
        datos = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _escribir_cache(cache_path: Path, datos: dict) -> None:
    """Escritura atómica: un cierre a medias no deja el JSON corrupto."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_name(cache_path.name + ".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache_path)
    except OSError:
        pass


def recordar_eleccion(cache_path: Path, track: Track) -> None:
    """
    Guarda en la caché el enlace elegido a mano para `track` ("manual": True),
    de modo que las búsquedas siguientes lo respeten (Status.MANUAL).
    Si track.youtube_url está vacío, quita la marca manual. No usa yt-dlp.
    """
    datos = _leer_cache(cache_path)
    key = cache_key(track)
    entrada = dict(datos.get(key) or {})
    if track.youtube_url:
        entrada.update({
            "url": track.youtube_url,
            "title": track.youtube_title,
            "score": track.score,
            "manual": True,
            "t": time.time(),   # para no pisarla con una búsqueda más antigua
        })
        if not entrada.get("cands") and track.candidates:
            entrada["cands"] = _cands_a_json(track.candidates)
    else:
        if not entrada.get("manual"):
            return
        entrada.pop("manual", None)
        entrada["t"] = time.time()
    datos[key] = entrada
    _escribir_cache(cache_path, datos)


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
        self._cache: dict[str, dict] = _leer_cache(cache_path)
        self._cambios: dict[str, float] = {}   # clave -> momento en que se buscó
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
        return cache_key(track)

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
        """
        Rellena youtube_url/youtube_title/score/status/candidates del track y lo
        devuelve. Con use_cache, una elección manual guardada gana (Status.MANUAL).
        """
        key = self._cache_key(track)
        hit = self._cache.get(key) if use_cache else None
        # Una entrada sin puntuación solo vale si es manual
        if hit and hit.get("url") and (hit.get("manual") or hit.get("score") is not None):
            track.youtube_url, track.youtube_title = hit["url"], hit.get("title") or ""
            track.score = hit.get("score")
            track.candidates = _cands_de_json(hit.get("cands"))
            if hit.get("manual"):
                track.status = Status.MANUAL
                return track
        else:
            cands = self.candidates(track, cancel)
            track.candidates = cands
            if not cands:
                track.youtube_url, track.youtube_title, track.score = "", "", None
                track.status = Status.FAILED
                return track
            best = cands[0]
            track.youtube_url, track.youtube_title, track.score = best.url, best.title, best.score
            self._cache[key] = {
                "url": best.url, "title": best.title, "score": best.score,
                "cands": _cands_a_json(cands, self.n_results),
            }
            self._cambios[key] = time.time()
        track.status = Status.OK if track.score >= UMBRAL_OK else Status.DOUBTFUL
        return track

    def save_cache(self) -> None:
        """
        Guarda solo lo buscado por esta instancia sobre lo que haya en disco: así
        no se pierden las elecciones manuales (recordar_eleccion) hechas mientras
        tanto, salvo que esta instancia haya vuelto a buscar la canción después.
        """
        if not self.cache_path or not self._cambios:
            return
        datos = _leer_cache(self.cache_path)
        for key, cuando in self._cambios.items():
            en_disco = datos.get(key) or {}
            if en_disco.get("manual") and (en_disco.get("t") or 0) > cuando:
                continue
            datos[key] = self._cache[key]
        _escribir_cache(self.cache_path, datos)
        self._cache.update(datos)
        self._cambios.clear()
