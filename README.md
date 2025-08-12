# YouTube → MP4 + MP3/WAV GUI (PySide6)

## Qué incluye
- `app.py`: GUI con PySide6 + qdarkstyle, progreso, logs, selector MP3/WAV, borrar MP4.
- `requirements.txt`
- `pyinstaller.spec` (opcional)
- `.github/workflows/build.yml`: compila el `.exe` en Windows (GitHub Actions).
- `assets/` para los íconos (`app.ico`/`app.png`).

## Cómo usar (local)
1. `python -m venv .venv && .\.venv\Scripts\activate` (Windows)
2. `pip install -r requirements.txt`
3. Asegúrate de tener `ffmpeg` en PATH.
4. `python app.py`

## Build en la nube (GitHub Actions)
1. Crea repo en GitHub y sube **todo** el contenido de esta carpeta.
2. (Opcional) Pon tu icono en `assets/app.ico` antes del push.
3. Ve a **Actions** y espera al build. Descarga el artefacto `dist`.
4. El `.exe` incluirá la GUI con tema oscuro. ffmpeg se instala en el runner y debe estar presente en la máquina final (o colócalo junto al exe si lo necesitas portable).

## Notas
- Usa solo con contenido propio o con permiso.
- El footer muestra: **© 2025 Gabriel Golker**.
- Si una URL es playlist, se procesa cada video individualmente.
