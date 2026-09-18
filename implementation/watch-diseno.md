[← Volver al índice](../README.md)

# `/watch`: decisiones de diseño

Por qué la skill está construida como está. Cada sección documenta una decisión
que no es obvia y el fallo concreto que evita.

## 1. El original gana a la traducción

Fijar el idioma de subtítulos es el error más caro de esta clase de herramienta.
Si el código pide `--sub-langs en.*`, un vídeo en español **con subtítulos en
español publicados** devuelve cero captions y cae al fallback de Whisper — que
cuesta dinero — o se queda solo con frames.

Pero el arreglo ingenuo — preferir el idioma del usuario — rompe el caso
contrario. YouTube ofrece la **traducción automática** de su reconocimiento de
voz a más de 150 idiomas. Con `es,en`, un webinar en inglés devolvía español
traducido por máquina: dos pasos con pérdida (reconocimiento y traducción)
donde bastaba uno. El agente lee el original sin problema y traduce mejor que
esa cadena.

**Solución.** Una sonda lee el inventario de pistas del `info.json` y
`choose_caption_track` aplica un orden fijo:

| Prioridad | Pista | Por qué |
|---|---|---|
| 1 | Manual en un idioma preferido | Escrita por una persona |
| 2 | Manual en el idioma del vídeo | Ídem, en el idioma original |
| 3 | Reconocimiento del idioma original (`<lang>-orig`) | Un solo paso con pérdida |
| 4 | Cualquier otra manual | Humana, aunque en un tercer idioma |
| 5 | Traducción automática en un idioma preferido | Último recurso |

Se descarga **solo esa pista**: una petición en vez de una por idioma, que es lo
que provoca los HTTP 429 de YouTube.

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

Los tests de rendimiento usan clips sintéticos que reproducen cada caso límite:
cortes con un keyframe por corte, un clip estático, y uno con doce cortes y **un
solo keyframe** para forzar la guarda de densidad.

**185 tests, sin red.**

## 7. Velocidad: medir antes de optimizar

Medido sobre dos vídeos reales, versión anterior contra la actual, misma red y
sin caché:

| | Antes | Después |
|---|---|---|
| Tutorial de 8 min — tiempo del script | 17.8 s | 5.8 s |
| Tutorial de 8 min — llamadas `Read` | 12 | 2 |
| Webinar de 55 min — tiempo del script | 59.4 s | 12.0 s |
| Webinar de 55 min — llamadas `Read` | 58 | 6 |
| Webinar de 55 min — informe | ~31k tokens | ~14k tokens |
| Webinar de 55 min — descarga | 104 MB | 26 MB |

Cada fila sale de una decisión con su medición detrás:

**Escenas sobre keyframes.** La detección de escenas decodificaba los ~98.000
frames del webinar (38 s). Con `-skip_frame nokey` solo se decodifican los 570
keyframes (2.4 s). Comparados uno a uno, cubren 51 de los 58 cambios; los otros
7 se revisaron visualmente y eran repeticiones o ruido. Además encontró 10
cambios graduales que el método completo no veía, y no gastó 18 frames en una
animación de 10 segundos. La decodificación por GPU fue **5 veces más lenta**
(178 s): el filtro de escenas corre en CPU y cada frame se copia de vuelta.

Una guarda protege el atajo: si los keyframes están de media a más de 10 s, o hay
un hueco de más de 30 s, se paga la decodificación completa. YouTube nunca pasa
de ~10 s; algunas grabadoras de pantalla escriben un solo keyframe.

**Descargar solo lo que se usa.** Los frames salen a 512 px, así que se pide
vídeo sin audio a 360-480p (lado corto, para que un vídeo vertical no baje a
270 px de ancho) en H.264, que es lo más rápido de decodificar. El audio se baja
aparte, en 48 kbps, y solo si no hay subtítulos. Todas las llamadas reutilizan
el `info.json` de la sonda en vez de volver a extraer.

**Dos carriles en paralelo.** Transcripción (red) y parte visual (CPU) no se
necesitan entre sí, así que corren a la vez. Si la descarga del vídeo falla pero
hay transcripción, el informe sale igual con los frames marcados como no
disponibles.

**Hojas de contacto.** Claude ve un frame llamando a `Read`, y cada llamada son
~50 tokens que el modelo **genera** antes de ver nada. Los tokens de imagen no
cambian (se facturan por píxel); lo que cambia es la generación. Una hoja de 3×3
lleva nueve frames por llamada, con la marca de tiempo dibujada en cada uno con
una fuente de mapa de bits propia — el `ffmpeg` de Homebrew no trae `drawtext`.
Las hojas se dimensionan dentro de lo que Claude acepta sin reescalar (≤1568 px
de lado, ≤1.19 MP), así que lo que se compone es exactamente lo que se ve.

**Transcripción sin duplicados.** Los subtítulos automáticos de YouTube repiten
la línea anterior en cada cue; el deduplicado compara palabras y se queda solo
con lo nuevo. Las líneas se agrupan en bloques de ≤10 s con una sola marca de
tiempo. Resultado: de ~29k a ~13k tokens en el webinar, sin perder texto. De
paso apareció un bug heredado: un cue que empieza con una línea de un solo
espacio se cortaba ahí, y la primera frase tras cada pausa salía ~3 s tarde.

**Sin preflight.** El `SKILL.md` ya no obliga a ejecutar `setup.py` antes de
mirar el vídeo. Sin `SETUP_COMPLETE` guardado, ese paso relanzaba el asistente
con preguntas **en cada sesión**. Ahora `watch.py` falla con un mensaje claro
solo si falta un binario.
