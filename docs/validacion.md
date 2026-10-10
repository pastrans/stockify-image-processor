# Validación del procesamiento de imágenes

Cómo comprobar que `processing.py` da buenos resultados antes de desplegar un cambio:
qué fotos usar, cómo ejecutar la prueba y en qué fijarse al revisar cada resultado.

## Cómo ejecutar la prueba

1. Pon las fotos de prueba en `samples/` (la carpeta no se sube a git).
2. Ejecuta `python cli.py samples out`.
3. Abre cada resultado de `out/` junto a su original y revísalo con la lista de abajo.

Cada vez que se cambie el algoritmo hay que repasar **todo** el conjunto, no solo la foto
que motivó el cambio: un ajuste que arregla un caso suele estropear otro.

## Escenarios que debe cubrir el conjunto de prueba

Cada escenario ataca una parte distinta del algoritmo. Una misma foto puede cubrir varios.

| # | Escenario | Qué pone a prueba |
|---|---|---|
| 1 | Producto mediano centrado, sin paredes visibles | El caso base: recorte y encuadre |
| 2 | Paredes de la caja visibles a los lados | Detección y reemplazo de paredes |
| 3 | Paredes del **mismo tono** que la cartulina (p. ej. rosa metálico sobre rosa, plateado sobre blanco) | Que la pared se distinga por textura y no solo por color |
| 4 | Producto oscuro sobre cartulina oscura | Que la máscara no pierda partes del producto |
| 5 | Producto claro sobre cartulina clara (p. ej. blanco sobre crema) | Igual que el anterior, en claro |
| 6 | Producto de color parecido a la cartulina | Que el producto no se confunda con el fondo |
| 7 | Producto transparente o brillante (vidrio, plástico, metal, charol) | Que reflejos y transparencias se conserven como parte del producto |
| 8 | Producto pequeño (ocupa menos del 10 % de la foto) | Límite de ampliación: no debe quedar borroso |
| 9 | Producto grande que llega al borde de la foto o queda cortado | Alineación con el borde y relleno de lo que falta |
| 10 | Varios objetos en una foto (pines, pares de calzado) | Que el recorte incluya todos los objetos |
| 11 | Cartulina curva con degradado de luz fuerte | Que el relleno continúe el degradado sin bandas |
| 12 | Algo ajeno a la caja en el borde (mesa, suelo, mano) | Que se detecte y reemplace como si fuera una pared |
| 13 | Fotos de **teléfonos distintos** y en vertical y horizontal | Resoluciones, proporciones, orientación EXIF y viñeteado del lente |
| 14 | Varios colores de cartulina | Que nada dependa de un color concreto |

Mínimo recomendado: unas 15 o 20 fotos que cubran todos los escenarios. Conviene
incluir el mismo producto fotografiado en dos cartulinas o ángulos distintos.

Las fotos deben pasarse **en tamaño original**: por cable, Google Photos/Drive o como
*documento* en WhatsApp. Enviadas como foto normal por WhatsApp llegan comprimidas y sin
EXIF, y no sirven para evaluar.

## Qué revisar en cada resultado

### Producto (lo más importante)
- [ ] **Está completo.** No le falta ninguna parte: puntas, tiras, cordones, asas, bordes
      transparentes.
- [ ] **No está alterado.** Conserva sus colores, brillos y reflejos reales; no tiene
      manchas ni zonas del color del fondo encima.
- [ ] **Su sombra real sigue ahí** y no se cortó de golpe.
- [ ] **Está nítido.** Si se ve borroso o pixelado, la foto original era demasiado lejana o
      de baja resolución.

### Encuadre
- [ ] El producto está **centrado** y ocupa aproximadamente el **80 %** del lado mayor.
- [ ] Con **varios objetos**, todos quedan dentro del recorte.
- [ ] Si el producto estaba **cortado** en la foto original, el corte coincide con el borde
      de la imagen y no queda "flotando" en medio del fondo.
- [ ] La imagen está **derecha** (no rotada 90°) y mide **1920×1920**.

### Fondo
- [ ] **No quedan restos de pared**: brillos metálicos, pliegues o franjas de otro color,
      sobre todo en las esquinas.
- [ ] **No se ven costuras**: ni rectángulos donde terminaba la foto original, ni bandas
      más claras u oscuras, ni líneas rectas que no estaban en la foto.
- [ ] El relleno tiene el **mismo color** que la cartulina real junto a él.
- [ ] El relleno tiene **grano o textura parecida** a la cartulina real: no se ve como una
      mancha lisa de plástico.
- [ ] El degradado de luz se ve **natural**, sin cambios bruscos.

### Errores
- [ ] Una foto sin producto (por ejemplo, solo cartulina) genera `error.json` en vez de una
      imagen sin sentido.

## Cómo calificar

| Resultado | Criterio |
|---|---|
| ✅ Bueno | Pasa toda la lista. Se publicaría tal cual. |
| ⚠️ Aceptable | Defecto menor que solo se nota buscándolo (p. ej. un resto tenue en una esquina). |
| ❌ Malo | Producto incompleto o alterado, pared claramente visible o costura evidente. |

Un cambio en el algoritmo solo se acepta si **ninguna foto pasa a ❌** y la mayoría quedan
en ✅. Anota los casos ⚠️ y ❌ en la sección *Estado* de `CLAUDE.md`.

## Recomendaciones al tomar las fotos

Muchos fallos se arreglan con una foto mejor y no cambiando el algoritmo:

- El producto debe verse **entero** y con algo de cartulina alrededor por todos los lados.
- **Varios objetos pequeños** (pines): agrúpalos juntos y ordenados, en el centro y sin
  dejar alguno suelto lejos del resto. Si están desperdigados, el recorte se vuelve enorme
  y cada objeto queda diminuto.
- Para productos pequeños, **acerca la cámara** en lugar de hacer zoom digital.
- Evita que aparezcan manos, cables u otros objetos dentro de la caja.
