---
name: diagnosticar-scraper
description: Diagnostica y repara la extracción de canciones de Spotify (spotyurl/spotify.py) o la elección de vídeos de YouTube (spotyurl/youtube.py) cuando salen 0 canciones, faltan canciones, los títulos/artistas/duraciones son incorrectos, o hay muchas coincidencias erróneas o dudosas. Úsalo cuando el usuario diga que no encuentra canciones, que Spotify cambió o que los enlaces no son la canción correcta.
---

# Diagnosticar extracción (Spotify) y match (YouTube)

## Piezas frágiles

| Archivo | Pieza | Qué hace |
|---|---|---|
| `spotyurl/spotify.py` | `SELECTORES_FILA` | Selectores de fila; se usa el primero que aparezca |
| | `_JS_LEER_FILAS` | Lee cada fila: índice (`closest('[aria-rowindex]')`), enlaces `/track/`, `/artist/`, `/album/` y la celda `m:ss` como duración |
| | `_JS_CONTENEDOR_SCROLL`, `ScrapeConfig` | Contenedor que hace scroll; paso, pausa y vueltas sin novedades antes de parar |
| `spotyurl/youtube.py` | `puntuar()`, `PALABRAS_SOSPECHOSAS`, `UMBRAL_OK` | Puntuación de los candidatos de yt-dlp |

Spotify virtualiza la lista: el DOM solo tiene unas cuantas filas a la vez. Por eso se lee
mientras se hace scroll. La clave para deduplicar es el `aria-rowindex`, que está en el
padre de `tracklist-row`, no en la fila.

## 1. Reproducir

```bash
cd "/c/Users/Luffy/Desktop/Spotify to You-rl" && PYTHONIOENCODING=utf-8 ./Spoty_to_you-rl/Scripts/python.exe -c "
from spotyurl.spotify import fetch_tracks
ts = fetch_tracks('<URL>', on_log=print)
print(len(ts)); [print(t) for t in ts[:3]]"
```

Playlists públicas de referencia: `37i9dQZF1DXcBWIGoYBM5M` (Today's Top Hits, 50 canciones) y
el álbum `4aawyAB9vmqN3uQ7FjRGTy` (18).

- **SpotifyError "No se encontraron canciones"**: no coincide ningún selector, o la página pide login.
- **El contador de únicas se estanca pronto**: el contenedor de scroll es incorrecto, o la pausa es demasiado corta.
- **Campos vacíos** (artistas, duración): cambiaron los enlaces o las celdas de la fila.

## 2. Inspeccionar el DOM real

Escribe un script en el scratchpad (no en el repo). Abre la URL con Playwright y evalúa sobre la
primera fila: `data-testid`, `aria-colindex` con su texto, los `href` de los enlaces y el
`aria-rowindex` del ancestro. Otra vía: el navegador integrado (carga antes la skill
`anthropic-skills:built-in-browser`) o activar `ScrapeConfig(headless=False)`.

Si aparece un banner de cookies, el código ya intenta pulsar "rechazar". Si la página pide
login, la playlist no es pública: díselo al usuario y sugiere la *Lista de texto* de la UI.

## 3. Arreglar

- Añade los selectores nuevos **al principio** y conserva los antiguos como fallback.
- Si el scroll se queda corto, ajusta primero `ScrapeConfig` (o los Ajustes de la UI). Toca la lógica solo si eso no basta.
- Para malas coincidencias, inspecciona los candidatos con `YouTubeMatcher().candidates(track)`:
  imprime score, duración, canal y título. Ajusta `puntuar()` y añade un caso a
  `tests/test_core.py`. Prueba siempre con `use_cache=False`.
- Respeta el estilo del código: nombres y comentarios en español.

## 4. Verificar

`python -m pytest`, y vuelve a ejecutar las playlists de referencia comparando el total con el que
muestra Spotify. Informa de qué cambiaste y con qué URL lo comprobaste.
