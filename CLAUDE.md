# Proyecto: stockify-image-processor

## Contexto
Stockify es un backend (Node + Express + TypeScript + Prisma/PostgreSQL, en otro repo) para
digitalizar el inventario de una tienda y exportarlo a Odoo 18+. Los productos tienen un
ProductTemplate (imagen principal → `image_1920` en Odoo) y ProductVariants (imagen opcional
→ `image_variant_1920`; si no tiene, usa la del template). Una sola imagen por template y una
opcional por variante: NO hay galería de varias fotos.

Las fotos se toman en una caja de luz de estudio de 40x40 cm con fondos de cartulina
intercambiables. Según el tamaño del producto, en la foto se ven las paredes de la caja (de
otro color) o el producto queda descentrado.

## Objetivo de este repo
Una AWS Lambda en Python, desplegada con AWS SAM, que procesa automáticamente cada foto
subida a S3 para dejar el producto centrado sobre el fondo de la cartulina, sin paredes.

## Flujo (contrato con el backend, basado solo en keys de S3)
1. El backend sube la foto a `tmp/{uuid}/original.{ext}` (bucket existente; `tmp/` es privado).
2. S3 → EventBridge dispara la Lambda (regla con wildcard `tmp/*/original.*`, que evita que
   la Lambda se dispare a sí misma).
3. La Lambda escribe `tmp/{uuid}/processed.jpg` o, si falla, `tmp/{uuid}/error.json`
   (`{"error": "..."}`) sin relanzar la excepción, para evitar reintentos. Además,
   `EventInvokeConfig.MaximumRetryAttempts: 0` evita reintentos por timeout/memoria (en esos
   casos no hay error.json: el backend debe tener su propio timeout).
4. La Lambda NO llama al backend. El backend consulta el estado con HeadObject sobre esas keys
   y, cuando el usuario guarda el producto, copia la imagen a su carpeta final pública.
5. Una Lifecycle Rule borra todo lo de `tmp/` con más de 1 día (imágenes huérfanas).

## Algoritmo de imagen (decisión clave)
NO quitar el fondo para poner uno artificial, NO transparencias, NO sombras sintéticas.
El producto, su sombra y su brillo reales se conservan. Se EXTIENDE el fondo real:
1. Corregir la orientación EXIF.
2. Máscara del producto con u2net vía `onnxruntime` directo (sin rembg: arrastra scipy y
   scikit-image). Se eligió u2net tras comparar con isnet-general-use (pierde partes de
   productos oscuros sobre gris) y u2netp (recorta trozos). Se conservan varios objetos de
   tamaño parecido (pines) y se quitan manchas sueltas.
3. Muestrear el color de la cartulina (LAB) en un anillo alrededor del producto.
4. Cartulina = relleno por inundación desde ese anillo, con tolerancia entre vecinos (sigue
   degradados de luz) + tope global de color + barrera de textura (las paredes de papel
   aluminio tienen mucho detalle fino; la cartulina es lisa). Paredes = lo que no es
   cartulina ni producto y toca el borde de la foto. NO se asume que siempre hay paredes.
5. Recorte cuadrado centrado en el producto (ocupa ~80%), con ampliación máxima 2x para
   productos pequeños; si el producto está cortado por un borde de la foto se alinea con ese
   borde. Lo que queda fuera de la foto (y una franja fina del borde, oscurecida por el
   lente) se marca como "por rellenar".
6. Relleno: cada píxel toma el color de la cartulina limpia más cercana, difuminado más
   cuanto más lejos (continúa el viñeteado y los degradados exactos del borde), con grano de
   la misma intensidad que la cartulina real y borde difuminado; nunca toca el producto.
   Se descartaron el polinomio (dejaba bandas en cartulinas curvas) y push-pull (escalón
   en fotos con viñeteado fuerte).
7. Salida en JPG de 1920x1920 (tamaño de `image_1920` en Odoo).
Plan B si el método clásico falla en algunos casos: outpainting con IA generativa.
Cualquier cambio al algoritmo se valida con `docs/validacion.md` (escenarios y checklist).
Muchos fallos se resuelven con mejores fotos (p. ej. pines agrupados), no con código.

## Estructura del repo
```
template.yaml               # SAM: imagen de contenedor, 2048 MB, 60 s, permisos solo sobre tmp/*, EventBridgeRule
samconfig.toml              # región, perfil AWS, BucketName, repos ECR automáticos
requirements-dev.txt        # entorno local (incluye boto3)
models/u2net.onnx           # modelo para el CLI local (en .gitignore; ver README)
src/
  Dockerfile                # imagen Lambda python3.12; descarga el modelo a /opt/models
  requirements.txt          # lo que se empaqueta (sin boto3: ya viene en el runtime)
  image_processor/
    processing.py           # función pura process_image(bytes) -> bytes (aquí vive el algoritmo)
    handler.py              # adaptador: evento EventBridge → get_object → process_image → put_object
cli.py                      # `python cli.py samples out`: procesa una carpeta en local, sin AWS
events/s3-put.json          # evento simulado para `sam local invoke`
infra/                      # JSON para configurar el bucket existente (EventBridge y lifecycle)
samples/  out/              # fotos de prueba y resultados (en .gitignore)
```

## Notas técnicas
- La lógica va en `processing.py`, independiente de Lambda, para iterar rápido con el CLI.
- La Lambda es imagen de contenedor (modelo ~176 MB + deps > 250 MB del zip). La ruta del
  modelo se lee de `U2NET_MODEL` (el Dockerfile la fija; en local cae a `models/u2net.onnx`).
  El usuario de deploy necesita `AmazonEC2ContainerRegistryFullAccess`.
- El bucket ya existe: hay que activar EventBridge en él (`put-bucket-notification-configuration`
  con `infra/bucket-notification.json`; ese comando reemplaza las notificaciones existentes).
- `sam local invoke` corre en Docker, pero lee y escribe en el S3 real.
- Odoo importa las imágenes por URL pública, así que la carpeta final debe ser pública; eso lo
  resuelve el backend, no esta Lambda.
- Comentarios de código en español.

## Estado
Algoritmo v1 implementado y validado con 32 fotos (dos teléfonos, 9 colores de cartulina,
paredes plateadas/negras/rosas, frasco transparente, objeto pequeño, botas). ~2.5 s por foto.
Imagen de contenedor construida y probada en local; falta desplegar.
Pendiente: restos leves de pared en algunas esquinas superiores (fotos con paredes plateadas
de reflejo marrón/gris, p. ej. IMG_20261009_175412 y PXL_20261009_233402238).
