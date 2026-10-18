"""Interfaz de línea de comandos (comportamiento clásico del script)."""

import argparse
import sys
import time
from pathlib import Path

from .export import default_name, to_txt
from .models import Status, app_data_dir
from .spotify import ScrapeConfig, SpotifyError, fetch_tracks, parse_source
from .youtube import YouTubeMatcher

CARPETA_PROYECTO = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="spotify_to_yourl",
        description="Convierte una playlist o álbum público de Spotify en enlaces de YouTube.",
    )
    ap.add_argument("url", nargs="?", help="Enlace de playlist o álbum de Spotify")
    ap.add_argument("-o", "--out", type=Path, default=CARPETA_PROYECTO, help="Carpeta del .txt de salida")
    ap.add_argument("--no-clipboard", action="store_true", help="No copiar cada enlace al portapapeles")
    ap.add_argument("--pause", type=float, default=1.0, help="Segundos entre copias al portapapeles (1)")
    ap.add_argument("--show-browser", action="store_true", help="Mostrar el navegador (debug)")
    ap.add_argument("--no-cache", action="store_true", help="Ignorar la caché de búsquedas")
    args = ap.parse_args(argv)

    url = args.url or input("Pega la URL de la playlist de Spotify: ").strip()
    if not parse_source(url):
        print("El enlace no es una playlist ni un álbum de Spotify.")
        return 1

    try:
        tracks = fetch_tracks(url, ScrapeConfig(headless=not args.show_browser), on_log=print)
    except SpotifyError as e:
        print(f"\n{e}")
        return 1

    print(f"\n{len(tracks)} canciones encontradas.\n" + "─" * 60)

    copiar = None
    if not args.no_clipboard:
        import pyperclip
        copiar = pyperclip.copy

    matcher = YouTubeMatcher(cache_path=app_data_dir() / "search_cache.json")
    ruta = args.out / default_name()
    try:
        for i, t in enumerate(tracks, 1):
            print(f"[{i:>4}/{len(tracks)}] {t.label}")
            try:
                matcher.match(t, use_cache=not args.no_cache)
            except Exception as e:
                t.status = Status.FAILED
                print(f"        Error YouTube: {e}")
            if not t.youtube_url:
                print("        Sin match en YouTube\n")
                continue
            aviso = "  (dudosa)" if t.status == Status.DOUBTFUL else ""
            print(f"        {t.youtube_url}{aviso}")
            if copiar:
                try:
                    copiar(t.youtube_url)
                except Exception as e:
                    print(f"        No se pudo copiar: {e}")
                if i < len(tracks):
                    time.sleep(args.pause)
    except KeyboardInterrupt:
        print("\nInterrumpido: se guardan los enlaces obtenidos hasta ahora.")
    finally:
        matcher.save_cache()
        n = to_txt(tracks, ruta)
        if n:
            print(f"\nArchivo guardado: {ruta}")
        else:
            ruta.unlink(missing_ok=True)

    ok = sum(t.status == Status.OK for t in tracks)
    dudosas = [t for t in tracks if t.status == Status.DOUBTFUL]
    fallidas = [t for t in tracks if t.status in (Status.FAILED, Status.PENDING)]
    print(f"\n{'─' * 60}\n  Total       : {len(tracks)}\n  Encontradas : {ok}"
          f"\n  Dudosas     : {len(dudosas)}\n  Sin match   : {len(fallidas)}")
    for etiqueta, lista in (("Dudosas (revisar)", dudosas), ("Sin match", fallidas)):
        if lista:
            print(f"\n  {etiqueta}:")
            for t in lista:
                print(f"    • {t.label}")
    print("─" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
