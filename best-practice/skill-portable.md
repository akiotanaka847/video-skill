[← Volver al índice](../README.md)

# Skills portables entre harnesses

Una skill que solo funciona en Claude Code se queda a medias. El patrón que
usa `/watch` la hace ejecutable también en Codex, Cursor o Gemini CLI sin
cambiar una línea de código.

## El problema

Los scripts empaquetados viven junto al `SKILL.md`, pero el script necesita
saber **su propia ruta absoluta** para poder invocarse. La solución obvia es una
variable del harness:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/watch.py"   # ❌ solo Claude Code
```

Esa variable no existe en ningún otro harness. La skill deja de funcionar en
cuanto sale de casa.

## El patrón

En vez de pedirle la ruta al harness, se le pide **al propio agente**, que ya la
conoce: acaba de leer el `SKILL.md` y su herramienta `Read` le devolvió la ruta.

> Set `SKILL_DIR` to the absolute path of the directory containing THIS
> SKILL.md you just Read — your harness told you that path in the Read result.
> The scripts are always a direct sibling of this file.

Y se añade una guarda que falla ruidosamente si el agente se equivoca:

```bash
SKILL_DIR="<ruta absoluta del directorio del SKILL.md leído>"
if [ ! -f "$SKILL_DIR/scripts/watch.py" ]; then
  echo "ERROR: scripts/watch.py no está bajo SKILL_DIR=$SKILL_DIR" >&2
  exit 1
fi
```

## Por qué funciona

| | Variable del harness | Ruta del `SKILL.md` leído |
|---|---|---|
| Claude Code | ✅ | ✅ |
| Codex / Cursor / Gemini CLI | ❌ | ✅ |
| Instalación global vs. por proyecto | Depende | ✅ |
| Ruta de caché de plugin versionada | Frágil | ✅ |

La información ya estaba en el contexto del agente. El error era ir a buscarla
a un sitio específico de un solo harness.

## Reglas que lo acompañan

1. **Guarda explícita antes del primer comando.** Un `SKILL_DIR` mal resuelto
   debe fallar con un mensaje que diga qué corregir, no con un `No such file`.
2. **Los scripts siempre hermanos del `SKILL.md`.** El patrón se apoya en esa
   invariante: si la rompes, deja de ser deducible.
3. **`python3` en macOS/Linux, `python` en Windows.** Ahí `python3` es el stub
   de la Microsoft Store y no ejecuta nada. Dilo explícitamente en el `SKILL.md`.
4. **`.skillignore` en la raíz.** Los escáneres de seguridad de instalación
   recorren el repo entero; sin él, tus tests y tu CI se auditan como si fueran
   código de ejecución.

Ver también: [implementation/watch-derivado.md](../implementation/watch-derivado.md).
