"""Interfaz de línea de comandos (comportamiento clásico del script)."""

import argparse
import sys
import threading
import time
from pathlib import Path

from .export import default_name, to_txt, unique_path
from .models import Status, Track
from .paths import CARPETA_ENLACES, cache_path, music_dir, safe_filename
from .spotify import ScrapeConfig, SpotifyError, fetch_tracks, parse_source
from .youtube import YouTubeMatcher


def _descargar(tracks: list[Track], carpeta: Path, formato: str = "mp3") -> None:
    """Descarga el audio en `carpeta`. Ctrl+C cancela de forma limpia."""
    from .download import download_tracks, pista_error

    n = sum(bool(t.youtube_url) for t in tracks)
    if not n:
        print("\nNo hay enlaces que descargar.")
        return

    print(f"\n{'─' * 60}\nDescargando {n} canciones en: {carpeta}")
    cancel = threading.Event()
    resultado = {}

    def trabajo() -> None:
        try:
            # Lista completa: la numeración de los archivos es la posición en la playlist
            resultado["r"] = download_tracks(tracks, carpeta, on_log=print, cancel=cancel, formato=formato)
        except Exception as e:
            resultado["error"] = e

    # La descarga va en un hilo: así Ctrl+C solo activa `cancel` y se espera a que termine
    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start()
    while hilo.is_alive():
        try:
            hilo.join(0.3)
        except KeyboardInterrupt:
            if not cancel.is_set():
                print("\nCancelando descarga (termina la canción en curso)…")
                cancel.set()

    if "error" in resultado:
        print(f"\nError en la descarga: {resultado['error']}")
        return
    r = resultado.get("r")
    if r is None:
        return
    print(f"\n{'─' * 60}\n  Descargadas    : {len(r.ok)}"
          f"\n  Ya existentes  : {len(r.skipped)}\n  Fallidas       : {len(r.failed)}")
    if r.failed:
        print("\n  Fallidas:")
        for t, motivo in r.failed:
            print(f"    • {t.label}: {motivo}")
        pista = pista_error(r.failed[0][1])
        if pista:
            print(f"\n  {pista}")
    print("─" * 60)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="spotify_to_yourl",
        description="Convierte una playlist o álbum público de Spotify en enlaces de YouTube.",
    )
    ap.add_argument("url", nargs="?", help="Enlace de playlist o álbum de Spotify")
    ap.add_argument("-o", "--out", type=Path, default=CARPETA_ENLACES,
                    help="Carpeta del .txt de salida (por defecto, enlaces/ del proyecto)")
    ap.add_argument("--no-clipboard", action="store_true", help="No copiar cada enlace al portapapeles")
    ap.add_argument("--pause", type=float, default=1.0, help="Segundos entre copias al portapapeles (1)")
    ap.add_argument("--show-browser", action="store_true", help="Mostrar el navegador (debug)")
    ap.add_argument("--no-cache", action="store_true", help="Ignorar la caché de búsquedas")
    ap.add_argument("--download", action="store_true",
                    help="Descargar también el audio en una carpeta con el nombre de la playlist")
    ap.add_argument("--audio-dir", type=Path, default=music_dir(),
                    help="Dónde crear la carpeta de audio (por defecto, Música)")
    ap.add_argument("--format", choices=["mp3", "m4a"], default="mp3", dest="audio_format",
                    help="Formato del audio descargado (por defecto, mp3)")
    args = ap.parse_args(argv)

    url = args.url or input("Pega la URL de la playlist de Spotify: ").strip()
    if not parse_source(url):
        print("El enlace no es una playlist ni un álbum de Spotify.")
        return 1

    nombres: list[str] = []
    try:
        tracks = fetch_tracks(url, ScrapeConfig(headless=not args.show_browser),
                              on_log=print, on_name=nombres.append)
    except SpotifyError as e:
        print(f"\n{e}")
        return 1

    print(f"\n{len(tracks)} canciones encontradas.\n" + "─" * 60)

    copiar = None
    if not args.no_clipboard:
        import pyperclip
        copiar = pyperclip.copy

    matcher = YouTubeMatcher(cache_path=cache_path())
    nombre = nombres[-1] if nombres else ""
    args.out.mkdir(parents=True, exist_ok=True)
    ruta = unique_path(args.out / default_name("txt", nombre))
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

    if args.download:
        _descargar(tracks, args.audio_dir / (safe_filename(nombre) or "Lista de canciones"), args.audio_format)
    return 0


if __name__ == "__main__":
    sys.exit(main())
