# Spotify → YouTube URL

Aplicación de escritorio (y CLI) que extrae **todas** las canciones de una playlist o álbum público de Spotify, busca cada una en YouTube y te da los enlaces: en una tabla revisable, copiados uno a uno al portapapeles (ideal para MediaHuman) y exportables a `.txt`, `.csv` o `.m3u`.

> No requiere API key de Spotify ni de YouTube.
> Usa **Playwright** para recorrer la playlist (cualquier tamaño) y **yt-dlp** para buscar en YouTube.

---

## ¿Cómo funciona?

```
Playlist / álbum de Spotify   ─┐
Lista de texto "Artista - Título" ─┤
                                 ▼
        Playwright abre open.spotify.com y hace scroll
        capturando título, artistas, álbum y duración
                                 │
                                 ▼
        yt-dlp pide varios candidatos por canción y elige
        el mejor (duración, canal oficial, sin covers/live…)
                                 │
         ┌───────────────┬───────┴─────────┬──────────────────┐
         ▼               ▼                 ▼                  ▼
   Tabla revisable   Portapapeles     youtube_links_FECHA.txt   Exportar .csv / .m3u
   (editar, reintentar) (MediaHuman)
```

---

## Instalación

Requiere Python **3.10+** (probado con 3.14 en Windows).

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

> **Linux:** para el portapapeles de la CLI necesitas `xclip` o `xsel` (`sudo apt install xclip`).

---

## Interfaz gráfica

```bash
python -m spotyurl.gui
```

En Windows también puedes hacer doble clic en **`abrir_app.bat`** (usa el entorno virtual `Spoty_to_you-rl/` si existe).

- **Enlace de Spotify**: pega una playlist o un álbum (`/playlist/…`, `/album/…`, `/intl-es/…`, `spotify:playlist:…`). El campo te indica si el enlace es válido.
- **Lista de texto**: pega canciones con formato `Artista - Título`, una por línea. Sirve para playlists privadas o cuando Spotify cambia su web.
- **Tabla**: las canciones aparecen en vivo mientras se extraen y cambian de estado:
  `pendiente → buscando → encontrada / dudosa / sin match / manual`.
  - Doble clic en el enlace para **pegar otro** a mano. Doble clic en el resto de la fila para abrir el vídeo.
  - Clic derecho: abrir, copiar, buscar a mano en YouTube, reintentar o quitar la fila.
  - Filtra por texto o por estado. Usa *Dudosas* para revisar las coincidencias inseguras.
- **Reintentar fallidas**, **Copiar todo** y **Exportar** (`.txt`, `.csv`, `.m3u`).
- **Copiar cada enlace al portapapeles**, con una pausa configurable entre copias, para MediaHuman.
- **Ajustes**: carpeta de salida, guardado automático del `.txt`, plantilla de búsqueda, número de candidatos, caché de búsquedas, parámetros de scroll y navegador visible (para depurar).
- Tema claro u oscuro.

La configuración se guarda automáticamente. La caché de búsquedas está en `%APPDATA%\spotyurl\`.

---

## Línea de comandos

```bash
python spotify_to_yourl.py "https://open.spotify.com/playlist/ID"
```

| Opción | Descripción |
|---|---|
| `-o, --out CARPETA` | Dónde guardar el `.txt` (por defecto, la carpeta del proyecto) |
| `--no-clipboard` | No copiar cada enlace al portapapeles |
| `--pause SEG` | Pausa entre copias al portapapeles (por defecto, 1) |
| `--show-browser` | Muestra el navegador durante la extracción (depuración) |
| `--no-cache` | Ignora la caché de búsquedas |

Si interrumpes con `Ctrl+C`, se guardan los enlaces obtenidos hasta ese momento.

---

## Uso con MediaHuman YouTube Downloader

1. Abre MediaHuman y activa **«Detectar enlaces del portapapeles»**.
2. Deja activada la opción **Copiar cada enlace al portapapeles** y pulsa *Convertir*.
3. Cada enlace encontrado entra en la cola de descarga.

Si prefieres esperar a que termine todo, arrastra el `.txt` a la ventana de MediaHuman.

---

## Estructura

```
spotyurl/
  models.py    Track, Status, utilidades de duración
  spotify.py   extracción con Playwright + parseo de enlaces y listas de texto
  youtube.py   búsqueda con yt-dlp, puntuación de candidatos, caché
  export.py    .txt / .csv / .m3u
  cli.py       línea de comandos
  gui.py       interfaz PySide6 (hilo de trabajo + tabla)
spotify_to_yourl.py   punto de entrada de la CLI
tests/                pytest (sin red)
```

Tests: `python -m pytest`

---

## Posibles errores

| Error | Causa | Solución |
|---|---|---|
| «No se encontraron canciones» | Playlist privada o Spotify cambió su web | Activa *Mostrar el navegador* en Ajustes, o pega la lista como texto |
| Faltan canciones al final | El scroll paró antes de tiempo | Sube *Pausa de scroll* o *Vueltas sin cambios* en Ajustes |
| Muchas «sin match» o errores de YouTube | yt-dlp desactualizado o límite de peticiones | `pip install -U yt-dlp` y reintenta las fallidas |
| `playwright._impl._errors.Error` | Chromium no instalado | `python -m playwright install chromium` |
| `pyperclip could not find a copy/paste mechanism` (CLI, Linux) | Falta `xclip` | `sudo apt install xclip` |

---

## Limitaciones

- Solo playlists y álbumes **públicos** de Spotify. Para lo demás, usa la *Lista de texto*.
- La elección del vídeo es automática. Revisa las *dudosas* y corrige a mano si hace falta.
- Depende de la web actual de `open.spotify.com`. Si Spotify la cambia, los selectores de `spotyurl/spotify.py` pueden necesitar ajustes.

---

## Licencia

MIT. Úsalo, modifícalo y compártelo libremente.
