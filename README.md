# video-skill

**Skills para Claude Code, empezando por darle ojos: `/watch`.**

Colección propia de skills empaquetadas como marketplace de Claude Code. La
primera, `/watch`, deja que Claude vea un vídeo — descarga, extrae frames,
transcribe y responde con lo que realmente pasa en pantalla.



## Instalación

```bash
/plugin marketplace add akiotanaka847/video-skill
/plugin install watch@video-skill
```

Requiere `yt-dlp` y `ffmpeg`; el instalador los pone solo en macOS vía Homebrew
y en Linux/Windows imprime el comando exacto. Clave de Whisper solo si vas a ver
vídeos sin subtítulos.

## SKILLS

| Skill | Qué hace | Docs |
|---|---|---|
| [`/watch`](plugins/watch/skills/watch/SKILL.md) | Ver un vídeo: frames + transcripción, con soporte de español, caché y notas | [implementación](implementation/watch-derivado.md) |

## Por qué existe este fork

El original está muy bien hecho, pero tenía el idioma de subtítulos fijado a
inglés en tres sitios. Un vídeo en español **con subtítulos en español perfectos**
devolvía cero captions y caía a Whisper de pago. Para quien trabaja en español ese
no es un detalle: es el camino feliz roto.

De ahí salieron cuatro cambios:

1. **Español de primera** — `WATCH_SUB_LANGS` (por defecto `es,en`), y para Whisper
   `--whisper-lang` y `--glossary` con tu vocabulario de dominio.
2. **Caché de transcripciones** — re-ver un vídeo es gratis e instantáneo.
3. **Persistencia** — `--save` escribe una nota markdown en tu repo e indexa el README.
4. **Modo lote** — expande playlists y listas de URLs.

## Uso rápido

```bash
/watch https://youtu.be/xxxx ¿qué gancho usan en los primeros 30 segundos?
```

```bash
/watch grabacion-bug.mov ¿qué está fallando aquí?
```

Guardando nota en un repo de conocimiento:

```bash
/watch https://youtu.be/xxxx --save ~/mi-repo/reports
```

## Configuración

`~/.config/video-skill/.env` (permisos `0600`). Si ya tenías el proyecto original
instalado, tus claves de `~/.config/watch/.env` se heredan solas.

| Variable | Por defecto | Qué controla |
|---|---|---|
| `GROQ_API_KEY` | — | Whisper vía Groq (preferido: más barato y rápido) |
| `OPENAI_API_KEY` | — | Whisper vía OpenAI (alternativa) |
| `WATCH_DETAIL` | `balanced` | `transcript` / `efficient` / `balanced` / `token-burner` |
| `WATCH_SUB_LANGS` | `es,en` | Idiomas de subtítulos, en orden de preferencia |
| `WATCH_WHISPER_LANG` | auto | Fuerza el idioma de Whisper (ISO-639-1) |
| `WATCH_GLOSSARY` | — | Términos de dominio como prior de decodificación |
| `WATCH_CACHE` | `true` | Caché de transcripciones |
| `WATCH_NOTES_DIR` | — | Destino por defecto de `--save` |

## REPORTS

Notas generadas por `--save` sobre este propio repo.

| Nota | Fecha | Fuente |
|---|---|---|
<!-- reports:start -->
<!-- reports:end -->

## Documentación

| Doc | Contenido |
|---|---|
| [best-practice/skill-portable.md](best-practice/skill-portable.md) | Cómo hacer una skill que funcione en cualquier harness |
| [implementation/watch-derivado.md](implementation/watch-derivado.md) | Qué se cambió del original y por qué |
| [CREDITS.md](CREDITS.md) | Atribución y licencia |
| [CHANGELOG.md](CHANGELOG.md) | Historial de versiones |

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

125 tests, sin red y sin binarios reales — los tests de preflight usan stubs en
el `PATH`, así que pasan en una máquina limpia y en CI.

## Licencia

MIT. Ver [LICENSE](LICENSE) y [CREDITS.md](CREDITS.md).
