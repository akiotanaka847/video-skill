[← Volver al índice](../README.md)

# `/watch`: qué cambia respecto al original

Trabajo derivado de [bradautomates/claude-video](https://github.com/bradautomates/claude-video)
(MIT). Atribución en [CREDITS.md](../CREDITS.md).

## 1. El idioma dejaba fuera al español

El original fijaba el inglés en tres sitios de `download.py`:

```python
"--sub-langs", "en.*",            # en fetch_captions y otra vez en download_url
preferred = [c for c in candidates
             if any(m in c.name for m in (".en.", ".en-US.", ".en-GB.", ".en-orig."))]
```

Consecuencia: un vídeo en español **con subtítulos en español publicados** no
devolvía captions. Caía al fallback de Whisper — que cuesta dinero — o se
quedaba solo con frames.

**Solución.** Un único ajuste, `WATCH_SUB_LANGS` (por defecto `es,en`), gobierna
las dos decisiones que antes estaban descoordinadas:

```python
def sub_lang_patterns(langs):
    patterns = ",".join(f"{c}.*" for c in langs)      # para yt-dlp
    markers  = [f".{c}." for c in langs]              # para elegir el .vtt
    markers += [f".{c}-orig." for c in langs]         # auto-subs al final
    return patterns, markers
```

El orden de la lista es el orden de preferencia, y las pistas manuales ganan a
las automáticas del mismo idioma porque sus marcadores van antes.

## 2. Whisper no aceptaba pistas

El payload solo mandaba `model`, `response_format` y `temperature`. Sin
`language`, el autodetect cambia de idioma a mitad de fichero en audio español
salpicado de nombres de producto en inglés. Sin `prompt`, los nombres propios
salían destrozados.

Se añaden ambos, con dos matices que importan:

- **`prompt` es un prior de decodificación, no una instrucción.** El modelo lo
  condiciona como si fuera el texto anterior al audio. Se le pasa una lista de
  términos separados por comas; una frase como "transcribe en español" no hace
  nada.
- **Se reenvía en cada chunk.** Whisper transcribe cada trozo aislado; un
  glosario enviado solo con el primero deja de sesgar a partir del segundo.

## 3. Nada sobrevivía a la sesión

El original escribe a un directorio temporal y el paso final indica `rm -rf`.
`notes.py` añade la otra mitad: una nota markdown con tabla de metadatos,
transcripción plegable y enlace de vuelta al índice, más una fila en la tabla
del README entre marcadores `<!-- reports:start -->` / `<!-- reports:end -->`.

**El resumen no lo puede escribir el script.** Lo produce el agente después de
leer los frames, que es necesariamente después de que el proceso termine. Así
que la nota se guarda con un marcador `<!-- RESUMEN: pendiente -->` y el
`SKILL.md` instruye al agente a sustituirlo con `Edit`. Un flag, sin estado
compartido entre procesos.

La indexación nunca lanza excepción: si falta el README o los marcadores,
devuelve `False`. Una comodidad no puede tumbar una ejecución que ya produjo una
nota buena.

## 4. Se pagaba dos veces por lo mismo

`cache.py` guarda transcripciones en `~/.cache/video-skill/transcripts/`.

Dos decisiones de diseño:

- **Se cachea la transcripción, nunca los frames.** Los frames dependen de
  `--detail`, `--fps`, `--resolution` y del rango: la clave sería enorme y casi
  nunca acertaría, y re-extraerlos es un paso local de ffmpeg. La transcripción
  es lo que cuesta dinero y red. Cachear lo caro y recalcular lo barato.
- **Se guarda sin filtrar por rango.** El filtro `--start/--end` se aplica al
  leer. Así, pedir otro tramo del mismo vídeo sale gratis en vez de fallar la
  caché.

La clave incluye idioma de subtítulos, idioma de Whisper y hash del glosario:
cambiar el glosario **debe** invalidar, o ajustarías el vocabulario, re-correrías
y recibirías en silencio el texto anterior.

Todo fallo de caché degrada a `None` en vez de lanzar: una caché corrupta debe
producir una ejecución más lenta, nunca una fallida.

## 5. El lote solo puede ser un resolutor

`batch.py` expande una playlist con `--flat-playlist` (una petición, no una por
vídeo) o lee un `.txt` de URLs, y devuelve la lista. **No ve nada**: ver un vídeo
significa meter frames en el contexto del modelo, y eso no se delega a un
subproceso. El bucle lo conduce el agente, un vídeo por turno.

## 6. Tests

Los 3 tests de `setup` fallaban en cualquier máquina sin `yt-dlp` instalado
(comprobado también contra el repo original). Ahora inyectan stubs ejecutables
en el `PATH`: comprueban la lógica de preflight, no si el binario existe.

Los tests de `config` además neutralizan el fichero heredado, que si no filtraba
el `~/.config/watch/.env` real del desarrollador dentro del test.

Los dos tests que afirmaban `sub-langs must be English-only` se sustituyen por
los que comprueban el comportamiento configurable: codificaban el bug.

**125 tests, sin red, sin binarios reales.**
