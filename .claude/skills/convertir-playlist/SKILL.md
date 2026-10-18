---
name: convertir-playlist
description: Convierte una playlist o álbum público de Spotify (o una lista "Artista - Título") en enlaces de YouTube usando la CLI del proyecto, o abre la interfaz gráfica. Úsalo cuando el usuario pida convertir/extraer una playlist, pegue un enlace open.spotify.com/playlist|album/..., o pida ejecutar o abrir la app.
---

# Convertir una playlist de Spotify a enlaces de YouTube

La lógica vive en el paquete `spotyurl/` (ver README, sección Estructura). Hay dos entradas:
- CLI: `spotify_to_yourl.py` → `spotyurl/cli.py`
- UI: `python -m spotyurl.gui` (o `abrir_app.bat`)

Python del proyecto: `Spoty_to_you-rl/Scripts/python.exe` (venv con uv). Si falta o falla un
import, usa la skill `preparar-entorno`.

## Si el usuario quiere la app

Lánzala en segundo plano y no esperes a que termine:

```bash
cd "/c/Users/Luffy/Desktop/Spotify to You-rl" && ./Spoty_to_you-rl/Scripts/python.exe -m spotyurl.gui
```

## Si quiere que lo hagas tú (CLI)

1. **URL**: playlist o álbum público (`/playlist/ID`, `/album/ID`, `/intl-xx/…`, `spotify:playlist:ID`).
   Las canciones sueltas (`/track/`) no están soportadas.
2. **Portapapeles**: por defecto la CLI copia cada enlace al portapapeles (para MediaHuman) y
   pisa lo que el usuario tenga copiado. Pregúntale. Si no lo quiere o no lo ha pedido,
   añade `--no-clipboard`.
3. **Ejecuta** en segundo plano, porque tarda unos 2-3 s por canción:

   ```bash
   cd "/c/Users/Luffy/Desktop/Spotify to You-rl" && PYTHONIOENCODING=utf-8 ./Spoty_to_you-rl/Scripts/python.exe -u spotify_to_yourl.py --no-clipboard "https://open.spotify.com/playlist/<ID>"
   ```

   Otras opciones: `-o CARPETA`, `--pause SEG`, `--show-browser`, `--no-cache`.
4. **Revisa la salida**:
   - En el log de scroll, el contador `únicas` debe coincidir con el número de canciones de Spotify.
   - El resumen final separa las encontradas, las **dudosas** (puntuación < 0.6: hay que revisarlas) y las que no tienen match.
   - Enlaza el `youtube_links_*.txt` generado.
5. Si salen 0 canciones o faltan muchas, usa la skill `diagnosticar-scraper`.

## Notas

- Los `youtube_links_*.txt`, `.csv` y `.m3u` están en `.gitignore`. No los añadas a git.
- La caché de búsquedas está en `%APPDATA%\spotyurl\search_cache.json`. Usa `--no-cache`
  cuando estés ajustando la puntuación.
- Si todas las búsquedas fallan (403, "not a bot", errores de extracción), lo más probable
  es que yt-dlp esté desactualizado: usa la skill `preparar-entorno`.
