# Changelog

## [1.0.0] — 2026-09-03

Primera versión. Derivado de
[bradautomates/claude-video](https://github.com/bradautomates/claude-video) v0.2.0 (MIT).

### Añadido
- `WATCH_SUB_LANGS` / `--lang`: idiomas de subtítulos configurables, `es,en` por defecto.
- `--whisper-lang`: fuerza el idioma de transcripción en vez de autodetectar.
- `--glossary` / `WATCH_GLOSSARY`: vocabulario de dominio como prior de decodificación, reenviado en cada chunk de audio.
- `cache.py`: caché de transcripciones en `~/.cache/video-skill`, invalidada por idioma y glosario.
- `notes.py` y `--save`: nota markdown por vídeo con indexación del README.
- `batch.py`: expansión de playlists y listas `.txt` de URLs.
- Herencia de claves desde `~/.config/watch/.env` de una instalación previa del original.
- Tests para los cuatro módulos nuevos.

### Corregido
- Idioma de subtítulos fijado a inglés en tres puntos de `download.py`.
- `_pick_subtitle` prefería marcadores ingleses en vez del orden configurado.
- Tests de `setup` que fallaban en máquinas sin `yt-dlp`; ahora usan stubs en `PATH`.
- Tests de `config` que podían leer el `.env` real del desarrollador.

### Cambiado
- Config de `~/.config/watch/.env` a `~/.config/video-skill/.env` (el anterior se lee como respaldo).
- Layout multi-plugin (`plugins/<nombre>/`) para alojar más skills.
