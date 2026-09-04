[← Volver al índice](../README.md)

# `/watch`: decisiones de diseño

Por qué la skill está construida como está. Cada sección documenta una decisión
que no es obvia y el fallo concreto que evita.

## 1. El idioma es configurable de punta a punta

Fijar el idioma de subtítulos es el error más caro de esta clase de herramienta.
Si el código pide `--sub-langs en.*`, un vídeo en español **con subtítulos en
español publicados** devuelve cero captions y cae al fallback de Whisper — que
cuesta dinero — o se queda solo con frames.

Peor aún, la decisión aparece en dos sitios distintos: qué le pides a `yt-dlp`, y
cuál de los `.vtt` descargados eliges después. Descoordinarlos es fácil.

**Solución.** Un único ajuste, `WATCH_SUB_LANGS` (por defecto `es,en`), gobierna
ambas:

```python
def sub_lang_patterns(langs):
    patterns = ",".join(f"{c}.*" for c in langs)      # para yt-dlp
    markers  = [f".{c}." for c in langs]              # para elegir el .vtt
    markers += [f".{c}-orig." for c in langs]         # auto-subs al final
    return patterns, markers
```

El orden de la lista es el orden de preferencia, y las pistas manuales ganan a
las automáticas del mismo idioma porque sus marcadores van antes en la lista.

## 2. Whisper recibe dos pistas, y ambas importan

- **`language`.** El autodetect es correcto en habla monolingüe limpia, pero
  cambia de idioma a mitad de fichero en audio español salpicado de nombres de
  producto en inglés. Forzarlo sale más barato que volver a transcribir.
- **`prompt` es un prior de decodificación, no una instrucción.** El modelo lo
  condiciona como si fuera el texto anterior al audio. Se le pasa una lista de
  términos separados por comas; una frase como "transcribe en español" no hace
  absolutamente nada.

**Y el glosario se reenvía en cada chunk.** Whisper transcribe cada trozo
aislado: un glosario enviado solo con el primero deja de sesgar a partir del
segundo, así que a partir del minuto 25 los nombres propios vuelven a salir mal.

## 3. El resumen lo escribe el agente, no el script

`--save` produce una nota markdown con tabla de metadatos, transcripción plegable
y enlace de vuelta al índice, más una fila en la tabla del README entre
marcadores `<!-- reports:start -->` / `<!-- reports:end -->`.

Pero el resumen no lo puede escribir el script: lo produce el agente **después**
de leer los frames, que es necesariamente después de que el proceso termine. Así
que la nota se guarda con un marcador `<!-- RESUMEN: pendiente -->` y el
`SKILL.md` instruye al agente a sustituirlo con `Edit`. Un flag, sin estado
compartido entre procesos.

La indexación nunca lanza excepción: si falta el README o los marcadores,
devuelve `False`. Una comodidad no puede tumbar una ejecución que ya produjo una
nota buena.

## 4. Se cachea lo caro, se recalcula lo barato

`cache.py` guarda transcripciones en `~/.cache/video-skill/transcripts/`.

- **Transcripción sí, frames no.** Los frames dependen de `--detail`, `--fps`,
  `--resolution` y del rango: la clave sería enorme y casi nunca acertaría, y
  re-extraerlos es un paso local de ffmpeg. La transcripción es lo que cuesta
  dinero y red.
- **Se guarda sin filtrar por rango.** El filtro `--start/--end` se aplica al
  leer. Así, pedir otro tramo del mismo vídeo sale gratis en vez de fallar la
  caché o, peor, devolver el tramo equivocado.

La clave incluye idioma de subtítulos, idioma de Whisper y hash del glosario:
cambiar el glosario **debe** invalidar, o ajustarías el vocabulario, re-correrías
y recibirías en silencio el texto anterior.

Todo fallo de caché degrada a `None` en vez de lanzar: una caché corrupta debe
producir una ejecución más lenta, nunca una fallida.

## 5. El lote solo puede ser un resolutor

`batch.py` expande una playlist con `--flat-playlist` (una petición, no una por
vídeo) o lee un `.txt` de URLs, y devuelve la lista.

**No ve nada.** Ver un vídeo significa meter frames en el contexto del modelo, y
eso no se delega a un subproceso. El bucle lo conduce el agente: un vídeo, una
respuesta, una nota, y el siguiente.

## 6. Los tests no dependen de la máquina

Dos trampas evitadas:

- **Binarios reales.** Los tests de preflight comprueban la lógica, no si
  `yt-dlp` está instalado. Inyectan stubs ejecutables en el `PATH`, así que pasan
  en una máquina limpia y en CI.
- **Config real del desarrollador.** Los tests de `config` neutralizan también el
  fichero heredado; si no, leerían el `~/.config/watch/.env` real de quien
  ejecuta y pasarían o fallarían según su máquina.

**125 tests, sin red, sin binarios reales.**
