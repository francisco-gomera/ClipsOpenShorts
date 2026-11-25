# F0: línea base de En vivo por bloques

## Alcance y límite de esta validación

Se usó `demo-openshorts.mp4` por indicación del usuario. `ffprobe` informó una
duración de 41.772698 s. Es una validación del camino del pipeline sobre una
fuente local corta; no permite extrapolar un bloque de 20–60 minutos. El
contenedor activo `openshorts-backend` aportó ffmpeg/ffprobe y dependencias
Python. El contenedor informó AMD Ryzen 5 7535HS, 12 CPU lógicas; Whisper usó
`small`, CPU (`WHISPER_DEVICE` sin override; valor predeterminado `cpu`),
`int8` (valor predeterminado) y número automático de hilos. El host Windows no
tenía `cv2`, ffmpeg ni ffprobe.

## Ejecución

```sh
AUTO_HOOK=1 CLIP_TARGET_MIN=5 CLIP_TARGET_MAX=8 SOURCE_CAP_MINUTES=2 CLIP_WORKERS=1 \
  python -u main.py -i demo-openshorts.mp4 -o <directorio-temporal> --generation-mode smart
```

| Etapa | Tiempo | Resultado |
| --- | ---: | --- |
| Ingesta/descarga | omitida | Fuente local; no se midió descarga |
| Whisper | 24.67 s | 41.8 s de video; RTF aproximado 0.59 |
| Selección | 0.00 s | Falló con `Clip detection failed`; el pipeline no encontró clips utilizables |
| Corte/reencuadre/subtítulos | no ejecutada | Selección fallida |
| Total hasta fallo | 24.97 s | No incluye render ni finalización exitosa |

La selección no completó cinco clips en este material. No hay evidencia de que
el suelo fuerce clips mediocres: en esta ejecución devolvió cero y falló. No se
pudo medir el reparto de reencuadre/subtítulos, ni evaluar video sin habla o la
selección visual Gemini. El tiempo de Whisper representa casi todo el total de
esta muestra fallida, pero no es una estimación para un bloque largo; adelantar
ASR a la captura requeriría su propia medición concurrente y F8 queda sin
implementar.

## Decisiones operativas iniciales

Se conserva 40 minutos como valor predeterminado y 2 bloques pendientes como
límite de aviso, ambos valores configurables del diseño. El demo valida entrada
local, la medición de ASR y el camino de fallo sin cuota artificial; no valida
rendimiento, calidad de clips ni backpressure para una sesión larga. Los
bloques nunca se descartan automáticamente.
