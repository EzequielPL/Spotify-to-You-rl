"""Interfaz de línea de comandos (comportamiento clásico del script)."""

import argparse
import sys
import threading
import time
from pathlib import Path

from .export import default_name, from_csv, to_txt, unique_path
from .models import Status, Track
from .paths import CARPETA_ENLACES, cache_path, music_dir, safe_filename
from .spotify import ScrapeConfig, SpotifyError, fetch_tracks, parse_source
from .youtube import YouTubeMatcher


def _descargar(tracks: list[Track], carpeta: Path, formato: str = "mp3", album: str = "",
               origen: str = "", mover_quitadas: bool = False) -> None:
    """Descarga el audio en `carpeta` (etiquetado con `album`). Ctrl+C cancela de forma limpia."""
    from .download import CARPETA_QUITADAS, download_tracks, pista_error

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
            resultado["r"] = download_tracks(tracks, carpeta, on_log=print, cancel=cancel,
                                           formato=formato, album=album, origen=origen,
                                           mover_quitadas=mover_quitadas)
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
    destino = f" (movidas a {CARPETA_QUITADAS}/)" if mover_quitadas and r.removed else ""
    print(f"\n{'─' * 60}\n  Nuevas         : {len(r.ok)}"
          f"\n  Ya existentes  : {len(r.skipped)}\n  Renumeradas    : {len(r.renamed)}"
          f"\n  Quitadas       : {len(r.removed)}{destino}\n  Fallidas       : {len(r.failed)}")
    if r.removed and not mover_quitadas:
        print("\n  Ya no están en la lista (usa --move-removed para moverlas a "
              f"{CARPETA_QUITADAS}/):")
        for archivo in r.removed:
            print(f"    • {archivo}")
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
    ap.add_argument("--format", choices=["mp3", "m4a"], default=None, dest="audio_format",
                    help="Formato del audio descargado (por defecto, mp3; con --sync, el de la carpeta)")
    ap.add_argument("--sync", type=Path, metavar="CARPETA",
                    help="Sincroniza una carpeta ya descargada con su playlist: descarga solo las "
                         "nuevas y renumera las demás (implica --download)")
    ap.add_argument("--move-removed", action="store_true",
                    help="Mover a la subcarpeta Quitadas/ las canciones que ya no están en la lista")
    ap.add_argument("--csv", type=Path, metavar="ARCHIVO",
                    help="Leer las canciones de un .csv (exportado por esta app o por Exportify) "
                         "en lugar de Spotify")
    args = ap.parse_args(argv)

    manifiesto = None
    if args.sync:
        from .download import ARCHIVO_MANIFIESTO, leer_manifiesto
        manifiesto = leer_manifiesto(args.sync)
        if manifiesto is None:
            print(f"La carpeta «{args.sync}» no tiene manifiesto ({ARCHIVO_MANIFIESTO}): "
                  "descárgala primero con --download para poder sincronizarla.")
            return 1
        if not args.url and not args.csv and not manifiesto.get("origen"):
            print(f"El manifiesto de «{args.sync}» no guarda el enlace de Spotify de la lista: "
                  "indícalo como argumento (o usa --csv).")
            return 1
        args.download = True

    formato = args.audio_format or (manifiesto or {}).get("formato") or "mp3"
    if formato not in ("mp3", "m4a"):
        formato = "mp3"

    url = ""
    nombres: list[str] = []
    if args.csv:
        try:
            nombre_csv, tracks = from_csv(args.csv)
        except (OSError, ValueError) as e:
            print(f"No se pudo leer el .csv: {e}")
            return 1
        nombres.append(nombre_csv)
        print(f"Leídas {len(tracks)} canciones de {args.csv}")
    else:
        url = args.url or (manifiesto or {}).get("origen") or \
            input("Pega la URL de la playlist de Spotify: ").strip()
        if not parse_source(url):
            print("El enlace no es una playlist ni un álbum de Spotify.")
            return 1
        try:
            tracks = fetch_tracks(url, ScrapeConfig(headless=not args.show_browser),
                                  on_log=print, on_name=nombres.append)
        except SpotifyError as e:
            print(f"\n{e}")
            return 1

    print(f"\n{len(tracks)} canciones encontradas.\n" + "─" * 60)

    nombre = nombres[-1] if nombres else ""
    if args.sync:
        carpeta = args.sync
        nombre = nombre or manifiesto.get("nombre") or carpeta.name
    else:
        carpeta = args.audio_dir / (safe_filename(nombre) or "Lista de canciones")

    # Las canciones ya descargadas en la carpeta reutilizan su enlace: solo se buscan las nuevas
    if args.download:
        from .download import aplicar_manifiesto, leer_manifiesto
        guardado = manifiesto or leer_manifiesto(carpeta)
        if guardado:
            n = aplicar_manifiesto(tracks, guardado)
            if n:
                print(f"{n} canciones ya descargadas reutilizan su enlace (no se buscan de nuevo).")

    copiar = None
    if not args.no_clipboard:
        import pyperclip
        copiar = pyperclip.copy

    matcher = YouTubeMatcher(cache_path=cache_path())
    args.out.mkdir(parents=True, exist_ok=True)
    ruta = unique_path(args.out / default_name("txt", nombre))
    try:
        for i, t in enumerate(tracks, 1):
            print(f"[{i:>4}/{len(tracks)}] {t.label}")
            if not t.youtube_url:   # las del .csv o del manifiesto ya traen enlace
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

    ok = sum(t.status in (Status.OK, Status.MANUAL) for t in tracks)
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
        _descargar(tracks, carpeta, formato, album=nombre, origen=url,
                   mover_quitadas=args.move_removed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
