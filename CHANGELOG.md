# Changelog

## [1.0.0] — 2026-09-03

Primera versión.

### Incluye
- `WATCH_SUB_LANGS` / `--lang`: idiomas de subtítulos configurables, `es,en` por defecto.
- `--whisper-lang`: fuerza el idioma de transcripción en vez de autodetectar.
- `--glossary` / `WATCH_GLOSSARY`: vocabulario de dominio como prior de decodificación, reenviado en cada chunk de audio.
- `cache.py`: caché de transcripciones en `~/.cache/video-skill`, invalidada por idioma y glosario.
- `notes.py` y `--save`: nota markdown por vídeo con indexación del README.
- `batch.py`: expansión de playlists y listas `.txt` de URLs.
- Herencia de claves desde un `~/.config/watch/.env` previo.
- Tests para los cuatro módulos nuevos.

### Notas
- Config en `~/.config/video-skill/.env` (un `~/.config/watch/.env` previo se lee como respaldo).
- Layout multi-plugin (`plugins/<nombre>/`) para alojar más skills.
- Tests herméticos: sin red y sin binarios reales, vía stubs en `PATH`.
