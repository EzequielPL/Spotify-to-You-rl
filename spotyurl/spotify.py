"""
Extracción de canciones desde open.spotify.com (playlists y álbumes públicos)
o desde una lista de texto pegada por el usuario.

La extracción usa Playwright sync: debe ejecutarse en un hilo sin event loop
de asyncio (el hilo principal de la CLI o un QThread de la UI).
"""


import re
import threading
from dataclasses import dataclass
from typing import Callable

from .models import Track, parse_duration

# Selectores a probar en orden de prioridad
SELECTORES_FILA = [
    '[data-testid="tracklist-row"]',
    'div[role="row"][aria-rowindex]',
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_RE_SOURCE = re.compile(r"(playlist|album)[/:]([A-Za-z0-9]+)")
_RE_VINETA = re.compile(r"^\s*(?:[•*\-]|\d+[.)])\s+")   # "1. ", "- ", "• " al inicio


class SpotifyError(Exception):
    """Error al extraer canciones de Spotify, con mensaje apto para el usuario."""


@dataclass
class ScrapeConfig:
    headless: bool = True
    scroll_step: int = 300
    scroll_pause: float = 0.7
    end_rounds: int = 8          # vueltas sin canciones nuevas antes de parar
    end_rounds_bottom: int = 3   # ídem, pero ya al final del scroll
    timeout_ms: int = 40_000


@dataclass
class Source:
    kind: str   # "playlist" | "album"
    id: str

    @property
    def url(self) -> str:
        return f"https://open.spotify.com/{self.kind}/{self.id}"


def parse_source(text: str) -> Source | None:
    """
    Reconoce enlaces y URIs de Spotify:
    https://open.spotify.com/intl-es/playlist/ID?si=..., spotify:album:ID, etc.
    """
    match = _RE_SOURCE.search(text.strip())
    return Source(match.group(1), match.group(2)) if match else None


def parse_text_list(text: str) -> list[Track]:
    """
    Una canción por línea, con formato "Artista - Título".
    Las líneas sin " - " se toman como título sin artista.
    """
    tracks = []
    for line in text.splitlines():
        line = _RE_VINETA.sub("", line).strip()
        if not line:
            continue
        if " - " in line:
            artist, title = line.split(" - ", 1)
            tracks.append(Track(title=title.strip(), artists=[artist.strip()]))
        else:
            tracks.append(Track(title=line))
    return tracks


_JS_LEER_FILAS = r"""
(sel) => [...document.querySelectorAll(sel)].map(row => {
    const wrap = row.closest('[aria-rowindex]');
    const idx = wrap ? parseInt(wrap.getAttribute('aria-rowindex'), 10) || 0 : 0;

    const trackA  = row.querySelector('a[href*="/track/"]');
    const titleEl = row.querySelector('[data-testid="internal-track-link"]') || trackA;
    const albumA  = row.querySelector('a[href*="/album/"]');
    let artists = [...new Set(
        [...row.querySelectorAll('a[href*="/artist/"]')]
            .map(a => a.innerText.trim()).filter(Boolean)
    )];

    const cells = [...row.querySelectorAll('[aria-colindex]')].map(c => c.innerText.trim());
    const duration = [...cells].reverse()
        .find(t => /^\d{1,2}:\d{2}(:\d{2})?$/.test(t)) || '';

    let title = titleEl ? titleEl.innerText.trim() : '';
    // Fallback: textos con dir="auto" (título, artista)
    if (!title || !artists.length) {
        const spans = [...row.querySelectorAll('span[dir="auto"], div[dir="auto"]')]
            .map(e => e.innerText.trim()).filter(t => t && !/^[\d:]+$/.test(t));
        if (!title) title = spans[0] || '';
        if (!artists.length && spans[1]) artists = spans[1].split(/,\s*/);
    }

    const m = trackA && trackA.getAttribute('href').match(/track\/([A-Za-z0-9]+)/);
    return {
        idx, title, artists, duration,
        album: albumA ? albumA.innerText.trim() : '',
        id: m ? m[1] : '',
    };
})
"""

_JS_NOMBRE = r"""
() => {
    const meta = document.querySelector('meta[property="og:title"]');
    const h1 = document.querySelector('[data-testid="entityTitle"] h1')
            || document.querySelector('main h1');
    const nombre = (meta && meta.getAttribute('content')) || (h1 && h1.innerText) || '';
    return nombre.trim();
}
"""

_JS_CONTENEDOR_SCROLL = r"""
(sel) => {
    const fila = document.querySelector(sel);
    let el = fila ? fila.parentElement : null;
    while (el && el !== document.body) {
        const oy = getComputedStyle(el).overflowY;
        if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 50) {
            return el;
        }
        el = el.parentElement;
    }
    return document.scrollingElement || document.documentElement;
}
"""

_JS_SCROLL = r"""
([el, paso]) => {
    el.scrollBy(0, paso);
    window.scrollBy(0, paso);
    return el.scrollTop + el.clientHeight >= el.scrollHeight - 4;
}
"""


def fetch_tracks(
    url: str,
    cfg: ScrapeConfig | None = None,
    on_track: Callable[[Track], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    on_name: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[Track]:
    """
    Abre la playlist/álbum, hace scroll progresivo (la lista está virtualizada)
    y devuelve las canciones en orden. on_track se llama con cada canción nueva;
    on_name, con el nombre de la playlist/álbum si se puede leer de la página.
    Lanza SpotifyError si no se encuentran filas.
    """
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

    cfg = cfg or ScrapeConfig()
    cancel = cancel or threading.Event()
    log = on_log or (lambda _msg: None)

    source = parse_source(url)
    if not source:
        raise SpotifyError("El enlace no es una playlist ni un álbum de Spotify.")

    vistos: dict[str, Track] = {}
    orden: dict[str, int] = {}

    log(f"Abriendo {source.url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.headless)
        try:
            ctx = browser.new_context(
                user_agent=USER_AGENT,
                locale="es-ES",
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()
            page.goto(source.url, wait_until="domcontentloaded", timeout=cfg.timeout_ms)

            selector = None
            for sel in SELECTORES_FILA:
                try:
                    page.wait_for_selector(sel, timeout=15_000)
                    selector = sel
                    break
                except PWTimeout:
                    if cancel.is_set():
                        return []
            if not selector:
                raise SpotifyError(
                    "No se encontraron canciones. ¿La playlist es pública? "
                    "Prueba con el navegador visible (Ajustes) o pega la lista como texto."
                )
            log(f"Selector activo: {selector}")

            # Nombre de la playlist/álbum (opcional: nunca rompe la extracción)
            try:
                nombre = (page.evaluate(_JS_NOMBRE) or "").strip()
            except Exception:
                nombre = ""
            if nombre:
                log(f"Nombre: {nombre}")
                if on_name:
                    on_name(nombre)

            # Rechazar cookies no esenciales si aparece el banner (no bloquea el scroll)
            try:
                page.click("#onetrust-reject-all-handler", timeout=1_500)
            except Exception:
                pass

            contenedor = page.evaluate_handle(_JS_CONTENEDOR_SCROLL, selector)

            sin_nuevas = 0
            vuelta = 0
            while not cancel.is_set():
                nuevas = 0
                for fila in page.evaluate(_JS_LEER_FILAS, selector):
                    if not fila["title"]:
                        continue
                    # aria-rowindex identifica la posición: conserva canciones repetidas
                    clave = f"#{fila['idx']}" if fila["idx"] else f"{fila['id']}|{fila['title']}"
                    if clave in vistos:
                        continue
                    track = Track(
                        title=fila["title"],
                        artists=fila["artists"],
                        duration_s=parse_duration(fila["duration"]),
                        album=fila["album"],
                        spotify_id=fila["id"],
                    )
                    vistos[clave] = track
                    orden[clave] = fila["idx"] or (10_000_000 + len(orden))
                    nuevas += 1
                    if on_track:
                        on_track(track)

                vuelta += 1
                sin_nuevas = 0 if nuevas else sin_nuevas + 1
                log(f"Vuelta {vuelta:>3} │ únicas: {len(vistos):>4} │ nuevas: {nuevas:>3}")

                al_final = page.evaluate(_JS_SCROLL, [contenedor, cfg.scroll_step])
                if sin_nuevas >= cfg.end_rounds or (al_final and sin_nuevas >= cfg.end_rounds_bottom):
                    break
                cancel.wait(cfg.scroll_pause)
        finally:
            browser.close()

    return [vistos[k] for k in sorted(vistos, key=orden.__getitem__)]
