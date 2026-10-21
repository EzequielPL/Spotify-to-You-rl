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
         ┌───────────────┬───────┴─────────┬──────────────────┬──────────────────┐
         ▼               ▼                 ▼                  ▼                  ▼
   Tabla revisable   Portapapeles   <Nombre de la lista>.txt  Exportar       Descargar audio
   (editar, reintentar) (MediaHuman)                     .csv / .m3u    (yt-dlp → .mp3)
```

---

## Instalación

Requiere Python **3.10+**. Funciona en **Windows** (probado con 3.14) y **macOS** (Intel y Apple Silicon).

### Windows

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### macOS

macOS no trae un Python actualizado: instálalo desde [python.org](https://www.python.org/downloads/macos/) o con Homebrew (`brew install python`). Después, en la carpeta del proyecto:

```bash
python3 -m venv Spoty_to_you-rl
Spoty_to_you-rl/bin/python -m pip install -r requirements.txt
Spoty_to_you-rl/bin/python -m playwright install chromium
```

> **Linux:** para el portapapeles de la CLI necesitas `xclip` o `xsel` (`sudo apt install xclip`).

**ffmpeg (opcional):** solo hace falta para que *Descargar audio* guarde en `.mp3`. Sin él, el audio se guarda tal cual lo da YouTube (`.m4a` o `.webm`).
- Windows: `winget install ffmpeg`
- macOS: `brew install ffmpeg`

---

## Interfaz gráfica

```bash
python -m spotyurl.gui
```

O con doble clic (usan el entorno virtual `Spoty_to_you-rl/` si existe):
- **Windows:** `abrir_app.bat`
- **macOS:** `abrir_app.command`. La primera vez, macOS puede bloquearlo por venir de internet: haz **clic derecho → Abrir → Abrir**. Si dice que no tiene permisos, ejecuta una vez `chmod +x abrir_app.command`.

En Mac, los atajos usan **Cmd** (Cmd+C copia los enlaces seleccionados, Cmd+, abre los Ajustes y la tecla de borrar quita filas).

- **Enlace de Spotify**: pega una playlist o un álbum (`/playlist/…`, `/album/…`, `/intl-es/…`, `spotify:playlist:…`). El campo te indica si el enlace es válido.
- **Lista de texto**: pega canciones con formato `Artista - Título`, una por línea. Sirve para playlists privadas o cuando Spotify cambia su web.
- **Tabla**: las canciones aparecen en vivo mientras se extraen y cambian de estado:
  `pendiente → buscando → encontrada / dudosa / sin match / manual`.
  - Doble clic en el enlace para **pegar otro** a mano. Doble clic en el resto de la fila para abrir el vídeo.
  - Clic derecho: abrir, copiar, buscar a mano en YouTube, reintentar o quitar la fila.
  - Filtra por texto o por estado. Usa *Dudosas* para revisar las coincidencias inseguras.
- **Reintentar fallidas**, **Copiar todo** y **Exportar** (`.txt`, `.csv`, `.m3u`).
- El `.txt` de enlaces se guarda con el **nombre de la playlist o álbum** (p. ej. `Mi playlist.txt`; si ya existe, `Mi playlist (2).txt`). Con *Lista de texto* se usa un nombre con la fecha.
- **⬇ Descargar audio**: descarga las canciones con enlace en `<carpeta de audio>/<Nombre de la playlist>/01 - Artista - Título.mp3`. La carpeta de audio es, por defecto, **Música** (`C:\Users\<tú>\Music` en Windows, `~/Music` en macOS) y se cambia en *Ajustes*. Antes te deja cambiar el nombre de la carpeta; las que ya existen se saltan. Requiere ffmpeg para `.mp3` (ver *Instalación*).
- **Copiar cada enlace al portapapeles**, con una pausa configurable entre copias, para MediaHuman.
- **Ajustes**: carpeta de salida (`.txt`), carpeta de audio (descargas), guardado automático del `.txt`, plantilla de búsqueda, número de candidatos, caché de búsquedas, parámetros de scroll y navegador visible (para depurar).
- Tema claro u oscuro.

La configuración se guarda automáticamente. La caché de búsquedas está en:
- Windows: `%APPDATA%\spotyurl\`
- macOS: `~/Library/Application Support/spotyurl/`

---

## Línea de comandos

```bash
python spotify_to_yourl.py "https://open.spotify.com/playlist/ID"
```

En macOS usa `python3` (o `Spoty_to_you-rl/bin/python`) en lugar de `python`.

| Opción | Descripción |
|---|---|
| `-o, --out CARPETA` | Dónde guardar el `.txt` (por defecto, la carpeta del proyecto) |
| `--no-clipboard` | No copiar cada enlace al portapapeles |
| `--pause SEG` | Pausa entre copias al portapapeles (por defecto, 1) |
| `--show-browser` | Muestra el navegador durante la extracción (depuración) |
| `--no-cache` | Ignora la caché de búsquedas |
| `--download` | Además, descarga el audio en `<carpeta de audio>/<Nombre de la playlist>/` (`.mp3` si hay ffmpeg) |
| `--audio-dir CARPETA` | Dónde crear la carpeta de audio (por defecto, Música; si no existe, el Escritorio) |

El `.txt` se nombra como la playlist o álbum. Si interrumpes con `Ctrl+C`, se guardan los enlaces obtenidos hasta ese momento.

---

## Uso con MediaHuman YouTube Downloader

1. Abre MediaHuman y activa **«Detectar enlaces del portapapeles»**.
2. Deja activada la opción **Copiar cada enlace al portapapeles** y pulsa *Convertir*.
3. Cada enlace encontrado entra en la cola de descarga.

Si prefieres esperar a que termine todo, arrastra el `.txt` a la ventana de MediaHuman.

MediaHuman también existe para macOS, así que el flujo es el mismo.

---

## Estructura

```
spotyurl/
  models.py    Track, Status, utilidades de duración
  spotify.py   extracción con Playwright + parseo de enlaces y listas de texto
  youtube.py   búsqueda con yt-dlp, puntuación de candidatos, caché
  export.py    .txt / .csv / .m3u
  download.py  descarga de audio con yt-dlp (+ ffmpeg para .mp3)
  cli.py       línea de comandos
  gui.py       interfaz PySide6 (hilo de trabajo + tabla)
spotify_to_yourl.py   punto de entrada de la CLI
abrir_app.bat         lanzador para Windows
abrir_app.command     lanzador para macOS
tests/                pytest (sin red, salvo SPOTYURL_NETWORK=1)
```

Tests: `python -m pytest`. GitHub Actions los ejecuta en Windows y macOS en cada push (`.github/workflows/tests.yml`).

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
