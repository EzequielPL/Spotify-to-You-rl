# Spotify → YouTube Downloader 

Script que extrae **todas** las canciones de cualquier playlist pública de Spotify, copia el enlace al portapapeles y guarda todos los enlaces en un archivo de texto (`.txt`).

> No requiere API key de Spotify ni de YouTube.  
> Usa **Playwright** para hacer scroll dinámico y capturar los datos en playlists de cualquier tamaño.

---

## ¿Cómo funciona?

```
Playlist pública de Spotify
        │
        ▼
  Playwright abre el embed
  y hace scroll automático
  hasta el final de la lista
        │
        ▼
  Extrae título + artista
  de cada canción
        │
        ▼
  Búsqueda en YouTube
  via yt-dlp
        │
        ├──▶ Copia enlace al clipboard  ──▶  MediaHuman lo detecta
        │
        └──▶ Guarda youtube_links_FECHA.txt
```

---

## Requisitos

- Python **3.10** o superior

### Instalar dependencias

```bash
pip install yt-dlp pyperclip playwright
python -m playwright install chromium
```

> **Linux:** Necesitas `xclip` o `xsel` para el clipboard:
> ```bash
> sudo apt install xclip
> ```
> **Windows / macOS:** No se necesita configuración extra.

---

## Uso

### Modo interactivo
```bash
python spotify_to_yourl.py
```

### Pasando la URL como argumento
```bash
python spotify_to_youtube.py 
```
Pegar url de playlist valida, eg: "https://open.spotify.com/playlist/0000000000000"

---

## Salida en consola

```
Abriendo Spotify embed con Playwright…

Haciendo scroll para cargar todas las canciones…
    Vuelta   1 │ Total acumulado:  125 │ Nuevas: 25
    Vuelta   2 │ Total acumulado:  150 │ Nuevas: 25
    Vuelta   3 │ Total acumulado:  173 │ Nuevas: 23
    Vuelta   4 │ Total acumulado:  173 │ Nuevas:  0
    Vuelta   5 │ Total acumulado:  173 │ Nuevas:  0
    ...

173 canciones encontradas.

[   1/173]  Bruno Mars - Lo Arriesgo Todo
            https://www.youtube.com/watch?v=XXXXXX
            Copiado al clipboard
            Esperando 1s…
...

───────────────────────────────────────────────────────
  Total canciones : 173
  Encontradas     : 171
  No encontradas  : 2
───────────────────────────────────────────────────────
```

---

## Archivo de salida

Se genera en la **misma carpeta del script**:

```
youtube_links_20240529_143022.txt
```

Cada línea contiene un enlace de YouTube:

```
https://www.youtube.com/watch?v=XXXXXX
https://www.youtube.com/watch?v=YYYYYY
https://www.youtube.com/watch?v=ZZZZZZ
```

---

## Configuración

Al inicio del script hay variables que puedes ajustar:

| Variable | Por defecto | Descripción |
|---|---|---|
| `PAUSA_ENTRE_CANCIONES` | `1` | Segundos de espera entre cada copia al clipboard |
| `MAX_RESULTADOS_YT` | `3` | Resultados de YouTube a evaluar por canción |
| `SCROLL_PAUSA` | `1.2` | Segundos de espera entre cada scroll |
| `SCROLL_INTENTOS_MAX` | `5` | Intentos sin nuevas canciones antes de detenerse |
| `HEADLESS` | `True` | `False` = ver el navegador en pantalla (útil para debug) |

---

## Util en conjunto con otras aplicaciones que descargan canciones desde YouTube

Eg: MediaHuma YouTube Dowloader

1. Abre **MediaHuman YouTube Downloader** antes de ejecutar el script.
2. Activa la opción **"Detectar enlaces del portapapeles"** en las preferencias.
3. Ejecuta el script. Cada enlace se copiará automáticamente y MediaHuman lo añadirá a la cola de descarga.

Alternativamente si prefieres esperar a que terminen de extraerse todas las canciones, simplemente puedes arrastrar el archivo `.txt` directamente a la ventana de MediaHuman. O utilizar los urls en otras apps.

---

## Posibles errores

| Error | Causa | Solución |
|---|---|---|
| Solo obtiene ~100 canciones | El scroll no terminó de cargar | Aumenta `SCROLL_INTENTOS_MAX` o pon `HEADLESS = False` para ver qué ocurre |
| `No se encontraron canciones` | Spotify cambió su estructura | Pon `HEADLESS = False` y verifica que la playlist carga |
| `pyperclip could not find a copy/paste mechanism` | Falta `xclip` en Linux | `sudo apt install xclip` |
| Canción no encontrada en YouTube | Sin match de búsqueda | El resumen final lista las canciones fallidas |
| `playwright._impl._errors.Error` | Chromium no instalado | `python -m playwright install chromium` |

---

## Debug: ver el navegador en pantalla

Si el script no encuentra canciones o se queda corto, cambia en el script:

```python
HEADLESS = False
```

Así verás exactamente qué hace Playwright en la página de Spotify y podrás identificar el problema.

---

## Limitaciones

- Solo funciona con playlists **públicas** de Spotify.
- El match con YouTube es automático; en casos raros puede no ser la versión exacta.
- Depende del formato actual de `open.spotify.com/embed` — si Spotify cambia su estructura, el script puede requerir ajustes.

---

## Licencia

MIT — úsalo, modifícalo y compártelo libremente.
