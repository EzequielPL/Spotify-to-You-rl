#!/usr/bin/env python3
"""
spotify_to_youtube.py  
──────────────────────────────
Extrae TODAS las canciones de una playlist pública de Spotify
(open.spotify.com/playlist/...)

Luego busca cada canción en YouTube, copia el enlace al clipboard
(funcional par combinar con otras apps que descargan de YouTube) y guarda todos los enlaces
en un archivo .txt junto al script.

Dependencias:
    pip install yt-dlp pyperclip playwright
    python -m playwright install chromium
"""

import re, sys, time, os
import pyperclip
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from yt_dlp import YoutubeDL

# Configuración interna

PAUSA_ENTRE_CANCIONES = 1    
MAX_RESULTADOS_YT = 3    
SCROLL_PASO = 300  
SCROLL_PAUSA = 0.7  
SCROLL_FIN_INTENTOS = 8    
HEADLESS = True 


# Selectores a probar en orden de prioridad
SELECTORES_FILA = [
    '[data-testid="tracklist-row"]',
    'div[role="row"][aria-rowindex]',
    'div[role="row"]',
    'div[aria-rowindex]',
]


def extraer_playlist_id(url: str) -> str:
    match = re.search(r"playlist/([A-Za-z0-9]+)", url)
    if not match:
        raise ValueError(f"No se pudo extraer el ID de playlist de: {url}")
    return match.group(1)


def leer_filas_visibles(page, selector: str) -> list[dict]:
    """
    Lee las filas visibles en el DOM y extrae título y artista.
    Usa múltiples estrategias internas porque Spotify cambia su HTML.
    """
    return page.evaluate("""
        (sel) => {
            const rows = document.querySelectorAll(sel);
            const result = [];
            rows.forEach(row => {
                // Índice de orden — aria-rowindex o posición en lista
                const idx = parseInt(
                    row.getAttribute('aria-rowindex') ||
                    row.getAttribute('data-index') || '0', 10
                );

                // Estrategia 1: data-testid específicos de Spotify
                const titleEl  = row.querySelector(
                    '[data-testid="internal-track-link"] span, ' +
                    '[data-testid="track-name"]'
                );
                const artistEl = row.querySelector(
                    '[data-testid="artist-name"], ' +
                    '[data-testid="artists-link"] span'
                );

                // Estrategia 2: links a /track/ y /artist/
                const trackLink  = row.querySelector('a[href*="/track/"]');
                const artistLink = row.querySelector('a[href*="/artist/"]');

                // Estrategia 3: spans con dir="auto"
                const spans = [...row.querySelectorAll('span[dir="auto"]')];

                let titulo  = "";
                let artista = "";

                titulo  = (titleEl  && titleEl.innerText.trim())  ||
                          (trackLink && trackLink.innerText.trim()) ||
                          (spans[0]  && spans[0].innerText.trim())  || "";

                artista = (artistEl  && artistEl.innerText.trim())  ||
                          (artistLink && artistLink.innerText.trim()) ||
                          (spans[1]  && spans[1].innerText.trim())   || "";

                // Fallback: todos los textos de la fila, ignorando números y duraciones
                if (!titulo) {
                    const textos = [...row.querySelectorAll('span, a')]
                        .map(el => el.innerText.trim())
                        .filter(t => t && !/^[\\d:]+$/.test(t));
                    titulo  = textos[0] || "";
                    artista = textos[1] || "";
                }

                if (titulo) {
                    result.push({ idx: idx || (result.length + 1), titulo, artista });
                }
            });
            return result;
        }
    """, selector)


def obtener_canciones_spotify(playlist_url: str) -> list[dict]:
    """
    Abre open.spotify.com/playlist/... con Playwright, hace scroll
    progresivo y captura cada fila mientras es visible en el DOM.
    """
    playlist_id = extraer_playlist_id(playlist_url)
    pagina_url  = f"https://open.spotify.com/playlist/{playlist_id}"

    canciones_por_idx: dict[int, dict] = {}

    print(f"\n Abriendo Spotify con Playwright…")
    print(f"    {pagina_url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="es-ES",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        try:
            page.goto(pagina_url, wait_until="networkidle", timeout=40_000)
        except PWTimeout:
            page.goto(pagina_url, wait_until="domcontentloaded", timeout=40_000)

        print(" Esperando contenido dinámico…")
        time.sleep(5)

        # Detectar qué selector funciona
        
        selector_activo = None
        for sel in SELECTORES_FILA:
            try:
                page.wait_for_selector(sel, timeout=6_000)
                count = len(page.query_selector_all(sel))
                if count > 0:
                    selector_activo = sel
                    print(f"  Selector activo: {sel!r} ({count} filas visibles)")
                    break
            except PWTimeout:
                continue

        if not selector_activo:
            print("  No se encontraron filas.")
            print("  ¿La playlist es pública? ¿Hay que hacer login?")
            print("  Pon HEADLESS = False para ver el navegador.")
            
            if HEADLESS:
                browser.close()
                return []
            else:
                time.sleep(20)
                browser.close()
                return []

        # ── Encontrar el contenedor scrollable ────────────────────────────────
        # En open.spotify.com el scroll principal suele estar en
        # div[data-testid="playlist-tracklist"] o en el root scrollable más grande
        
        scroll_js = """
            (sel) => {
                const fila = document.querySelector(sel);
                if (!fila) return document.documentElement;
                // Subir por el DOM hasta encontrar overflow scroll/auto
                let el = fila.parentElement;
                while (el && el !== document.body) {
                    const oy = window.getComputedStyle(el).overflowY;
                    if ((oy === 'auto' || oy === 'scroll') &&
                         el.scrollHeight > el.clientHeight + 50) {
                        return el;
                    }
                    el = el.parentElement;
                }
                // Fallback: el elemento con mayor scrollHeight en la página
                let mejor = document.documentElement;
                document.querySelectorAll('*').forEach(e => {
                    const oy = window.getComputedStyle(e).overflowY;
                    if ((oy === 'auto' || oy === 'scroll') &&
                         e.scrollHeight > mejor.scrollHeight) {
                        mejor = e;
                    }
                });
                return mejor;
            }
        """
        scroll_handle = page.evaluate_handle(scroll_js, selector_activo)

        # Verificar cuál es el contenedor
        
        info_container = page.evaluate("""
            (el) => ({
                tag     : el.tagName,
                id      : el.id,
                testid  : el.getAttribute('data-testid') || '',
                scrollH : el.scrollHeight,
                clientH : el.clientHeight,
            })
        """, scroll_handle)
        print(f"Contenedor scroll: <{info_container['tag']}> "
              f"data-testid={info_container['testid']!r} "
              f"scrollH={info_container['scrollH']}px")

        # Scroll y captura de canciones
        
        print(f"\n Scrolleando y capturando filas…\n")

        sin_nuevas   = 0
        scroll_total = 0
        # Contador local para filas sin aria-rowindex
        contador_seq = 0

        while sin_nuevas < SCROLL_FIN_INTENTOS:
            filas = leer_filas_visibles(page, selector_activo)
            antes = len(canciones_por_idx)

            for fila in filas:
                # Si la fila no tiene aria-rowindex usamos un índice secuencial
                # basado en título y artista como clave única
                
                clave_texto = f"{fila['titulo']}|||{fila['artista']}"
                idx = fila["idx"]

                # Para selectores sin aria-rowindex, usar hash del texto
                if idx == 0 or idx == (filas.index(fila) + 1):
                    # Usar índice basado en texto para no sobreescribir
                    idx = hash(clave_texto) & 0xFFFFFF

                if idx not in canciones_por_idx and fila["titulo"]:
                    canciones_por_idx[idx] = {
                        "titulo":  fila["titulo"],
                        "artista": fila["artista"],
                        "_orden":  len(canciones_por_idx),  # orden real de aparición
                    }

            despues = len(canciones_por_idx)
            nuevas  = despues - antes
            max_visible = max((f["idx"] for f in filas), default=0)

            print(f"Scroll {scroll_total:>6}px │ "
                  f"Únicas: {despues:>4} │ "
                  f"Nuevas: {nuevas:>3} │ "
                  f"Fila visible max: #{max_visible}")

            sin_nuevas = 0 if nuevas > 0 else sin_nuevas + 1

            # Scroll en el contenedor correcto Y en window (doble seguridad)
            page.evaluate("""
                ([container, paso]) => {
                    container.scrollBy(0, paso);
                    window.scrollBy(0, paso);
                }
            """, [scroll_handle, SCROLL_PASO])
            scroll_total += SCROLL_PASO
            time.sleep(SCROLL_PAUSA)

        browser.close()

    # Ordenar por orden real de aparición
    canciones = sorted(canciones_por_idx.values(), key=lambda c: c["_orden"])
    return [{"titulo": c["titulo"], "artista": c["artista"]} for c in canciones]


def buscar_en_youtube(titulo: str, artista: str) -> str | None:
    query    = f"{titulo} {artista} official audio"
    ydl_opts = {
        "quiet":True,
        "no_warnings":True,
        "extract_flat":True,
        "default_search": "ytsearch",
        "noplaylist":True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f"ytsearch{MAX_RESULTADOS_YT}:{query}", download=False)

    if not result or "entries" not in result:
        return None
    entries = [e for e in result["entries"] if e]
    return f"https://www.youtube.com/watch?v={entries[0]['id']}" if entries else None


def guardar_enlaces(enlaces: list[str], carpeta: str) -> str:
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta  = os.path.join(carpeta, f"youtube_links_{ts}.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(enlaces) + "\n")
    return ruta


def main():
    if len(sys.argv) > 1:
        playlist_url = sys.argv[1].strip()
    else:
        playlist_url = input("Pega la URL de la playlist de Spotify: ").strip()

    if not playlist_url:
        print(" No ingresaste ninguna URL.")
        sys.exit(1)

    try:
        canciones = obtener_canciones_spotify(playlist_url)
    except Exception as e:
        print(f"\n Error al obtener la playlist: {e}")
        sys.exit(1)

    if not canciones:
        print("\n No se encontraron canciones.")
        print(" Tip: pon HEADLESS = False y corre el diagnostico_spotify.py primero.")
        sys.exit(1)

    print(f"\n {len(canciones)} canciones encontradas.\n")
    print("─" * 60)

    carpeta  = os.path.dirname(os.path.abspath(__file__))
    enlaces  = []
    fallidos = []

    for i, cancion in enumerate(canciones, 1):
        titulo  = cancion["titulo"]
        artista = cancion["artista"]
        print(f"[{i:>4}/{len(canciones)}] {titulo} — {artista}")

        try:
            url = buscar_en_youtube(titulo, artista)
        except Exception as e:
            print(f" Error YouTube: {e}")
            url = None

        if url:
            enlaces.append(url)
            pyperclip.copy(url)
            print(f" - {url}")
            print(f" - Copiado al clipboard")
            if i < len(canciones):
                print(f" - Esperando {PAUSA_ENTRE_CANCIONES}s…\n")
                time.sleep(PAUSA_ENTRE_CANCIONES)
        else:
            fallidos.append(f"{titulo} — {artista}")
            print(f"Sin match en YouTube\n")

    if enlaces:
        ruta_txt = guardar_enlaces(enlaces, carpeta)
        print(f"\n - Archivo guardado:\n    {ruta_txt}")

    print(f"\n{'─'*60}")
    print(f"  Total    : {len(canciones)}")
    print(f"  - Encontradas : {len(enlaces)}")
    print(f"  - Fallidas    : {len(fallidos)}")
    if fallidos:
        print("\n  Sin match en YouTube:")
        for f in fallidos:
            print(f"    • {f}")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    main()
