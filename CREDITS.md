# Créditos y atribución

## Obra original

La skill `/watch` de este repositorio es un **trabajo derivado** de:

- **[bradautomates/claude-video](https://github.com/bradautomates/claude-video)** — de Bradley Bonanno, licencia MIT.

El diseño base es suyo: el dial `--detail`, el presupuesto de frames por duración,
la selección de frames por escena, el troceado de audio para Whisper, la
resolución portable de `SKILL_DIR` y la estructura del informe. Si te resulta útil
este repo, la mayor parte del mérito arquitectónico es del proyecto original —
dale una estrella allí.

La licencia MIT exige conservar el aviso de copyright original. Está en
[LICENSE](LICENSE) junto al de las modificaciones, y así se queda.

## Qué cambia en este derivado

| Área | Original | Aquí |
|---|---|---|
| Idioma de subtítulos | `en.*` fijo en tres sitios | `WATCH_SUB_LANGS` / `--lang`, por defecto `es,en` |
| Selección de `.vtt` | Prefiere marcadores ingleses | Orden de preferencia configurable, manual antes que `-orig` |
| Whisper | Sin `language` ni `prompt` | `--whisper-lang` y `--glossary` (prior de decodificación), reenviados en cada chunk |
| Transcripciones | Se recalculan siempre | Caché en `~/.cache/video-skill`, invalidada por idioma y glosario |
| Salida | Directorio temporal, se borra | `--save` escribe una nota markdown e indexa el README |
| Playlists | Manual, vídeo a vídeo | `batch.py` expande playlists y listas `.txt` |
| Config | `~/.config/watch/.env` | `~/.config/video-skill/.env`, heredando claves del anterior |
| Tests | 3 fallos en máquina sin `yt-dlp` | Herméticos vía stubs en PATH; 125 en verde |

Detalle técnico en [implementation/watch-derivado.md](implementation/watch-derivado.md).

## Dependencias externas

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — Unlicense
- [FFmpeg](https://ffmpeg.org/) — LGPL/GPL según compilación
- APIs de transcripción de [Groq](https://groq.com/) y [OpenAI](https://openai.com/) (opcionales)
