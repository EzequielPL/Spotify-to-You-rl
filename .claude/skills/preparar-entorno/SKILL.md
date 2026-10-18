---
name: preparar-entorno
description: Crea, repara o actualiza el entorno Python del proyecto (venv Spoty_to_you-rl con yt-dlp, playwright + Chromium, pyperclip, PySide6 y pytest). Úsalo ante ModuleNotFoundError, cuando Playwright no encuentra el navegador, cuando yt-dlp falla al buscar o avisa de que está desactualizado, o cuando el usuario pide instalar o actualizar dependencias.
---

# Preparar el entorno

- El venv está en `Spoty_to_you-rl/`, en la raíz del proyecto (Windows, Python 3.14, creado con uv) y en `.gitignore`.
- Las dependencias están en `requirements.txt` y en `pyproject.toml` (extra `dev` = pytest).

Usa siempre el Python del venv:

```bash
cd "/c/Users/Luffy/Desktop/Spotify to You-rl"
PY=./Spoty_to_you-rl/Scripts/python.exe
```

## 1. Diagnóstico

```bash
$PY -c "import yt_dlp, playwright, pyperclip, PySide6; print(yt_dlp.version.__version__, PySide6.__version__)"
```

## 2. Crear el venv (solo si falta)

```bash
uv venv Spoty_to_you-rl      # o: python -m venv Spoty_to_you-rl
```

Si el venv existe pero está roto, confirma con el usuario antes de borrarlo.

## 3. Instalar

```bash
$PY -m pip install -r requirements.txt pytest
$PY -m playwright install chromium
```

Si el venv no tiene pip: `uv pip install --python "$PY" -r requirements.txt pytest`.

## 4. yt-dlp desactualizado

YouTube rompe yt-dlp a menudo, y yt-dlp avisa cuando tiene más de 90 días. Si las búsquedas
fallan en bloque o aparece ese aviso, actualízalo:

```bash
$PY -m pip install -U yt-dlp
```

## 5. Verificar

```bash
$PY -m pytest -q
$PY -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); print(b.version); b.close(); p.stop()"
```

Informa al usuario de las versiones instaladas.
