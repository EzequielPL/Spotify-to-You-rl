# Spotify → YouTube URL

Aplicación de escritorio (y CLI) que extrae **todas** las canciones de una playlist o álbum público de Spotify, busca cada una en YouTube y te da los enlaces: en una tabla revisable, copiados uno a uno al portapapeles (ideal para MediaHuman) y exportables a `.txt`, `.csv` o `.m3u`.

> No requiere API key de Spotify ni de YouTube.
> Usa **Playwright** para recorrer la playlist (cualquier tamaño) y **yt-dlp** para buscar en YouTube.

---

## Inicio rápido (sin programar)

1. **Descarga el proyecto**: en GitHub, botón verde **Code → Download ZIP**. Descomprime el `.zip` donde quieras (por ejemplo, en el Escritorio).
2. **Instala** con doble clic (solo la primera vez; si lo repites, actualiza las dependencias):
   - **Windows:** `instalar.bat`
   - **macOS:** `instalar.command`. La primera vez macOS puede bloquearlo por venir de internet: haz **clic derecho → Abrir → Abrir**.

   El instalador comprueba que tengas Python 3.10+ (si no, te dice cómo instalarlo), crea el entorno virtual `Spoty_to_you-rl/`, instala las dependencias (incluido ffmpeg, para convertir a `.mp3`) y el navegador Chromium que usa Playwright. Vuelve a ejecutarlo de vez en cuando: actualiza yt-dlp, que YouTube obliga a renovar a menudo.
3. **Abre la app** con doble clic en `abrir_app.bat` (Windows) o `abrir_app.command` (macOS).
4. Pega el enlace de la playlist y pulsa *Convertir*. Los enlaces (`.txt`, `.csv`, `.m3u`) quedan en la carpeta **`enlaces/`** del proyecto y el audio descargado en tu carpeta **Música**.

> **No muevas los lanzadores** (`instalar.*`, `abrir_app.*`) fuera de la carpeta del proyecto: buscan el entorno virtual a su lado. Si quieres abrir la app desde el Escritorio, crea un **acceso directo** (Windows: clic derecho → *Crear acceso directo*) o un **alias** (macOS: clic derecho → *Crear alias*) y mueve ese.

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

## Instalación manual

Si prefieres no usar `instalar.bat` / `instalar.command`, puedes hacer lo mismo a mano.

Requiere Python **3.10+**. Funciona en **Windows** (probado con 3.14) y **macOS** (Intel y Apple Silicon).

### Windows

```bat
python -m venv Spoty_to_you-rl
Spoty_to_you-rl\Scripts\python -m pip install -r requirements.txt
Spoty_to_you-rl\Scripts\python -m playwright install chromium
```

(O, sin entorno virtual: `pip install -r requirements.txt` y `python -m playwright install chromium`.)

### macOS

macOS no trae un Python actualizado: instálalo desde [python.org](https://www.python.org/downloads/macos/) o con Homebrew (`brew install python`). Después, en la carpeta del proyecto:

```bash
python3 -m venv Spoty_to_you-rl
Spoty_to_you-rl/bin/python -m pip install -r requirements.txt
Spoty_to_you-rl/bin/python -m playwright install chromium
```

> **Linux:** para el portapapeles de la CLI necesitas `xclip` o `xsel` (`sudo apt install xclip`).

**ffmpeg:** no hay que instalarlo aparte. Viene con el paquete `imageio-ffmpeg` (en `requirements.txt`) y es el que convierte a `.mp3`/`.m4a`. Si tienes ffmpeg instalado en el sistema (`winget install ffmpeg` / `brew install ffmpeg`), se usa ese.

---

## Interfaz gráfica

```bash
python -m spotyurl.gui
```

O con doble clic (usan el entorno virtual `Spoty_to_you-rl/`; si no existe, te piden ejecutar antes el instalador):
- **Windows:** `abrir_app.bat`
- **macOS:** `abrir_app.command`. La primera vez, macOS puede bloquearlo por venir de internet: haz **clic derecho → Abrir → Abrir**. Si dice que no tiene permisos, ejecuta una vez `chmod +x abrir_app.command instalar.command`.

En Mac, los atajos usan **Cmd** (Cmd+C copia los enlaces seleccionados, Cmd+, abre los Ajustes y la tecla de borrar quita filas).

- **Enlace de Spotify**: pega una playlist o un álbum (`/playlist/…`, `/album/…`, `/intl-es/…`, `spotify:playlist:…`). El campo te indica si el enlace es válido.
- **Lista de texto**: pega canciones con formato `Artista - Título`, una por línea. Sirve para playlists privadas o cuando Spotify cambia su web.
- **Tabla**: las canciones aparecen en vivo mientras se extraen y cambian de estado:
  `pendiente → buscando → encontrada / dudosa / sin match / manual`.
  - Doble clic en el enlace para **pegar otro** a mano. Doble clic en el resto de la fila para abrir el vídeo.
  - Clic derecho: abrir, copiar, buscar a mano en YouTube, reintentar o quitar la fila.
  - Filtra por texto o por estado. Usa *Dudosas* para revisar las coincidencias inseguras.
- **Reintentar fallidas**, **Copiar todo** y **Exportar** (`.txt`, `.csv`, `.m3u`).
- El `.txt` de enlaces se guarda en la carpeta **`enlaces/`** del proyecto (se cambia en *Ajustes*) con el **nombre de la playlist o álbum** (p. ej. `Mi playlist.txt`; si ya existe, `Mi playlist (2).txt`). Con *Lista de texto* se usa un nombre con la fecha.
- **⬇ Descargar audio**: descarga las canciones con enlace en `<carpeta de audio>/<Nombre de la playlist>/01 - Artista - Título.mp3`. La carpeta de audio es, por defecto, **Música** (`C:\Users\<tú>\Music` en Windows, `~/Music` en macOS) y se cambia en *Ajustes*. Antes te deja cambiar el nombre de la carpeta y elegir el **formato**: `.mp3` (por defecto, compatible con todo) o `.m4a` (AAC, sin recomprimir). Se recuerda el último elegido. Las canciones que ya existen en ese formato se saltan.
- **Copiar cada enlace al portapapeles**, con una pausa configurable entre copias, para MediaHuman.
- **Ajustes**: carpeta de salida (`.txt`/`.csv`/`.m3u`; por defecto `enlaces/`), carpeta de audio (descargas), guardado automático del `.txt`, plantilla de búsqueda, número de candidatos, caché de búsquedas, parámetros de scroll y navegador visible (para depurar).
- Tema claro u oscuro.

La configuración se guarda automáticamente. La caché de búsquedas está en:
- Windows: `%APPDATA%\spotyurl\`
- macOS: `~/Library/Application Support/spotyurl/`

---

## Línea de comandos

```bash
python spotify_to_yourl.py "https://open.spotify.com/playlist/ID"
# o, equivalente:
python -m spotyurl "https://open.spotify.com/playlist/ID"
```

En Windows usa `Spoty_to_you-rl\Scripts\python` y en macOS `Spoty_to_you-rl/bin/python` (o `python3`) en lugar de `python`, para usar el entorno virtual que crea el instalador.

| Opción | Descripción |
|---|---|
| `-o, --out CARPETA` | Dónde guardar el `.txt` (por defecto, `enlaces/` dentro del proyecto) |
| `--no-clipboard` | No copiar cada enlace al portapapeles |
| `--pause SEG` | Pausa entre copias al portapapeles (por defecto, 1) |
| `--show-browser` | Muestra el navegador durante la extracción (depuración) |
| `--no-cache` | Ignora la caché de búsquedas |
| `--download` | Además, descarga el audio en `<carpeta de audio>/<Nombre de la playlist>/` |
| `--format mp3\|m4a` | Formato del audio descargado (por defecto, `mp3`) |
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
instalar.bat          instalador para Windows (venv + dependencias + Chromium)
instalar.command      instalador para macOS
abrir_app.bat         lanzador de la interfaz para Windows
abrir_app.command     lanzador de la interfaz para macOS
spotify_to_yourl.py   punto de entrada de la CLI (igual que python -m spotyurl)
requirements.txt      dependencias
pyproject.toml        metadatos del paquete y configuración de pytest
enlaces/              aquí se guardan los .txt / .csv / .m3u (no se suben a git)
Spoty_to_you-rl/      entorno virtual (lo crea el instalador; no se sube a git)
tests/                pytest (sin red, salvo SPOTYURL_NETWORK=1)
spotyurl/
  __main__.py   python -m spotyurl → CLI
  paths.py      rutas, nombres de archivo y carpeta enlaces/
  models.py     Track, Status, utilidades de duración
  spotify.py    extracción con Playwright + parseo de enlaces y listas de texto
  youtube.py    búsqueda con yt-dlp, puntuación de candidatos, caché
  export.py     .txt / .csv / .m3u
  download.py   descarga de audio con yt-dlp (+ ffmpeg incluido para .mp3/.m4a)
  cli.py        línea de comandos
  assets/
    icon.svg    icono de la app
  gui/          interfaz PySide6 (python -m spotyurl.gui)
    __main__.py          python -m spotyurl.gui
    app.py               punto de entrada de la interfaz
    ventana.py           ventana principal
    dialogo_ajustes.py   diálogo de Ajustes
    dialogo_descarga.py  diálogo de Descargar audio (carpeta y formato)
    workers.py           hilos de trabajo (extracción, búsqueda, descarga)
    modelo.py            modelo de la tabla de canciones y su filtro
    tema.py              tema claro / oscuro
    ajustes.py           ajustes persistentes (QSettings)
    constantes.py        constantes compartidas
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
