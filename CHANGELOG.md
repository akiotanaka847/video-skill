# Changelog

## [1.1.0] — 2026-09-18

Velocidad. Webinar de 55 min: 59 s → 12 s de script, 58 → 6 lecturas de
imagen, 31k → 14k tokens de informe. Detalle en
[implementation/watch-diseno.md](implementation/watch-diseno.md).

### Añadido
- Hojas de contacto (`sheets.py`): hasta 9 frames por imagen con su marca de tiempo; `--no-sheets` para desactivarlas.
- Detección de escenas sobre keyframes, con guarda de densidad que vuelve a la decodificación completa cuando los keyframes son escasos.
- Transcripción y parte visual en paralelo.
- Whisper troceado en fragmentos de ≤10 min, cortados en pausas y transcritos en paralelo.
- Reintento con extracción fresca cuando YouTube responde 403 a una descarga reutilizada.
- Borrado automático de directorios temporales propios con más de 24 h.

### Cambiado
- Elección de subtítulos: el idioma original gana a una traducción automática; se descarga una sola pista.
- Descarga de vídeo sin audio a la resolución que necesitan los frames; audio pequeño aparte solo si hace falta Whisper.
- La transcripción se agrupa en bloques de ≤10 s con una marca de tiempo por bloque.
- El `SKILL.md` ya no ejecuta un preflight ni un paso de limpieza en cada uso.
- Si los frames fallan pero hay transcripción, el informe sale igualmente.
- Caché de transcripciones v2: las entradas de la 1.0.0 (traducidas y duplicadas) se ignoran.

### Corregido
- Subtítulos rodantes de YouTube: cada frase aparecía dos veces.
- Un cue que empezaba con una línea de un espacio se descartaba; la primera frase tras una pausa salía ~3 s tarde.
- Con `es,en`, un vídeo en inglés recibía la traducción automática al español.

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
