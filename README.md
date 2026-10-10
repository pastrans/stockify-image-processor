# stockify-image-processor

Lambda (Python 3.12, AWS SAM) que procesa cada foto subida a `tmp/{uuid}/original.{ext}`
y escribe `tmp/{uuid}/processed.jpg` o `tmp/{uuid}/error.json`. Cómo validar los resultados: `docs/validacion.md`. Ver `CLAUDE.md` para el
contexto completo y el algoritmo.

## Cómo encaja todo

- **`processing.py`** es el algoritmo de imagen. Es Python normal: se ejecuta en tu PC con
  `cli.py`, sin AWS.
- **`template.yaml`** describe la infraestructura en AWS: la Lambda, su rol (permisos) y la
  regla de EventBridge que la dispara. No se crea nada a mano en la consola.
- **AWS SAM** (Serverless Application Model) es la herramienta que lee `template.yaml`:
  - `sam build` construye una **imagen de contenedor** (Docker) con el código, sus
    dependencias y el modelo de IA. Se usa imagen y no zip porque el modelo pesa ~176 MB
    y el zip de Lambda está limitado a 250 MB. La receta está en `src/Dockerfile`.
  - `sam deploy` lo sube y crea o actualiza todo en AWS como un *stack* de CloudFormation
    (visible en la consola → CloudFormation). Si borras el stack, se borra todo lo que creó.
- El **bucket ya existe** y no lo gestiona SAM, así que su configuración (activar
  EventBridge y borrar `tmp/` a diario) se hace una sola vez con los comandos del paso 5.

Orden recomendado: **paso 1 (local)** para trabajar el algoritmo. Los pasos 2 a 6 solo
hacen falta cuando quieras desplegarlo en AWS.

---

## 1. Ejecutar en local (sin AWS)

Solo necesitas Python 3.12. Todos los comandos son de PowerShell, desde la carpeta del proyecto.

```powershell
# 1. Instalar Python 3.12 (la misma versión que usa Lambda)
py install 3.12

# 2. Crear el entorno virtual (borra antes el .venv viejo si existe)
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
py -3.12 -m venv .venv

# 3. Activarlo. Si PowerShell lo bloquea, ejecuta una sola vez:
#    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.venv\Scripts\Activate.ps1

# 4. Instalar dependencias
pip install -r requirements-dev.txt

# 5. Descargar el modelo que ubica el producto (~176 MB, una sola vez; no va en git)
New-Item -ItemType Directory -Force models
Invoke-WebRequest -OutFile models\u2net.onnx `
  -Uri https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx
```

Para procesar fotos, ponlas en `samples/` (jpg, png o webp) y ejecuta:

```powershell
python cli.py samples out
```

Los resultados quedan en `out/`. Cada vez que abras una terminal nueva, vuelve a activar
el entorno con `.venv\Scripts\Activate.ps1`. En VS Code, selecciona el intérprete
`.venv` con *Python: Select Interpreter*.

---

## 2. Credenciales de AWS

### Reglas básicas

- **El usuario root no se usa para trabajar.** No le crees access keys. Actívale MFA
  (consola → nombre de cuenta arriba a la derecha → *Security credentials* → *Assign MFA*)
  y úsalo solo para tareas de cuenta (facturación, cerrar la cuenta…).
- **Usuario vs. rol.** Un *usuario* IAM es una identidad con claves (para una persona o un
  servidor). Un *rol* es un conjunto de permisos que asume un servicio de AWS, como la
  Lambda, y no tiene claves.

### Las tres identidades

| Identidad | Tipo | Para qué | Quién la crea |
|---|---|---|---|
| `stockify-deployer` | Usuario IAM | Tú, desde tu PC: `sam deploy`, comandos `aws` | Tú, en la consola (2.1) |
| Rol de la Lambda | Rol IAM | La Lambda lee y escribe en `tmp/` | SAM, automáticamente |
| `stockify-backend` | Usuario IAM | El backend sube fotos y las copia a la carpeta final | Tú, en la consola (2.2) |

### 2.1 Crear `stockify-deployer` (para este proyecto)

1. Entra a la consola con root → servicio **IAM** → **Users** → **Create user**.
2. Nombre: `stockify-deployer`. No marques el acceso a la consola. **Next**.
3. **Attach policies directly** y marca:
   - `AWSCloudFormationFullAccess`
   - `AWSLambda_FullAccess`
   - `IAMFullAccess`: SAM necesita crear el rol de la Lambda.
   - `AmazonEventBridgeFullAccess`
   - `AmazonS3FullAccess`: para el bucket donde SAM sube el código y para configurar el bucket de Stockify.
   - `CloudWatchLogsFullAccess`
   - `AmazonEC2ContainerRegistryFullAccess`: la imagen de la Lambda se sube a ECR, el
     registro de contenedores de AWS.
4. **Create user**. Luego abre el usuario → pestaña **Security credentials** →
   **Create access key** → *Command Line Interface (CLI)* → copia el *Access key ID* y el
   *Secret access key*. El secreto solo se muestra una vez.

Esas claves **no van en el repo**. Se guardan con la AWS CLI (paso 3).

### 2.2 Crear `stockify-backend` (para el otro repo)

Igual que el anterior, pero en el paso 3 elige **Create inline policy** → pestaña **JSON** y
pega esto. Hay una línea `Resource` por cada carpeta final del backend; ajústalas a
las que use:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TmpSubirYConsultarEstado",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::stockify-media-storage-dev/tmp/*"
    },
    {
      "Sid": "CarpetasFinales",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::stockify-media-storage-dev/product-templates/*",
        "arn:aws:s3:::stockify-media-storage-dev/product-variants/*",
        "arn:aws:s3:::stockify-media-storage-dev/categories/*",
        "arn:aws:s3:::stockify-media-storage-dev/users/*"
      ]
    },
    {
      "Sid": "ListarParaRecibir404",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::stockify-media-storage-dev"
    }
  ]
}
```

Si más adelante el backend usa una carpeta nueva, hay que añadirla aquí; si no, S3
responde `AccessDenied`. La alternativa más simple es un solo
`arn:aws:s3:::stockify-media-storage-dev/*` en `CarpetasFinales`, que da acceso a todo el
bucket (incluido `tmp/`).

Sus access keys van en el `.env` del backend (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_REGION` y el nombre del bucket). `HeadObject` usa el permiso `s3:GetObject`, y
`CopyObject` necesita `GetObject` en el origen y `PutObject` en el destino.

---

## 3. Instalar las herramientas de AWS

Requiere Docker Desktop abierto (para `sam build`).

```powershell
winget install Amazon.AWSCLI
winget install Amazon.SAM-CLI
# Cierra y vuelve a abrir la terminal, luego:
aws --version
sam --version

# Guardar las claves de stockify-deployer en un perfil llamado "stockify"
aws configure --profile stockify
#   AWS Access Key ID:     (la del paso 2.1)
#   AWS Secret Access Key: (la del paso 2.1)
#   Default region name:   la región del bucket, p. ej. us-east-1
#   Default output format: json

aws sts get-caller-identity --profile stockify   # debe mostrar .../user/stockify-deployer
```

Las claves quedan en `%USERPROFILE%\.aws\credentials`, fuera del proyecto.

---

## 4. Configurar el proyecto

La Lambda **no usa variables de entorno**: el bucket y la key llegan en el evento. Solo
hay que editar:

- `samconfig.toml`: `region` (la del bucket; se ve en la consola de S3) y `BucketName` en
  las dos líneas `parameter_overrides`.
- `events/s3-put.json`: el mismo nombre de bucket (en `resources` y en `detail.bucket.name`).

---

## 5. Configurar el bucket existente (una sola vez)

Al bucket se le aplican dos ajustes:

| Ajuste | Para qué | Archivo |
|---|---|---|
| **Notificaciones → EventBridge** | Que S3 avise a EventBridge cada vez que se crea un archivo. Sin esto la Lambda nunca se dispara. | `infra/bucket-notification.json` |
| **Lifecycle (ciclo de vida)** | Que S3 borre solo lo que hay en `tmp/` con más de 1 día (fotos que nadie llegó a guardar). | `infra/bucket-lifecycle.json` |

Cada ajuste tiene un comando `get-...` (leer, no cambia nada) y otro `put-...` (escribir).
El `put` **reemplaza** lo que hubiera, por eso primero se lee.

**a) Definir el nombre del bucket.** Hay que repetirlo en cada terminal nueva, porque la
variable se pierde al cerrarla:

```powershell
$BUCKET = "stockify-media-storage-dev"
```

**b) Ver la configuración actual:**

```powershell
aws s3api get-bucket-notification-configuration --bucket $BUCKET --profile stockify
aws s3api get-bucket-lifecycle-configuration    --bucket $BUCKET --profile stockify
```

| Resultado | Significado |
|---|---|
| No imprime nada | No hay notificaciones configuradas: puedes seguir. |
| Error `NoSuchLifecycleConfiguration` | No hay reglas de lifecycle: puedes seguir. |
| Imprime un JSON | Ya hay algo configurado: añádelo al JSON de `infra/` antes del paso c. |
| `AccessDenied` | `$BUCKET` está vacía o el perfil tiene otras claves (`aws sts get-caller-identity --profile stockify`). |

**c) Aplicar.** Si todo va bien, ninguno de los dos imprime nada:

```powershell
aws s3api put-bucket-notification-configuration --bucket $BUCKET --profile stockify `
  --notification-configuration file://infra/bucket-notification.json

aws s3api put-bucket-lifecycle-configuration --bucket $BUCKET --profile stockify `
  --lifecycle-configuration file://infra/bucket-lifecycle.json
```

**d) Comprobar.** Vuelve a ejecutar los dos `get` del paso b:

- El de notificaciones debe mostrar `"EventBridgeConfiguration": {}`.
- El de lifecycle debe mostrar la regla `borrar-tmp-1-dia`.

También se ve en la consola: S3 → bucket → pestaña **Properties** → *Amazon EventBridge*
en **On**, y pestaña **Management** → *Lifecycle rules*.

---

## 6. Build, prueba y deploy

```powershell
sam validate --lint          # revisa template.yaml
sam build                    # construye la imagen en Docker (la primera vez tarda unos minutos)
```

**Opcional: probar la Lambda en Docker antes de desplegar.** Corre en tu PC pero usa el S3
real con las credenciales de `stockify-deployer`:

```powershell
aws s3 cp samples\foto.jpg s3://$BUCKET/tmp/prueba-local/original.jpg --profile stockify
sam local invoke ImageProcessorFunction -e events/s3-put.json
aws s3 ls s3://$BUCKET/tmp/prueba-local/ --profile stockify   # debe aparecer processed.jpg
aws s3 cp s3://$BUCKET/tmp/prueba-local/processed.jpg out\processed.jpg --profile stockify
```

1. `aws s3 cp` copia una foto de tu PC (`samples\foto.jpg`) al bucket, en la ruta que
   usaría el backend.
2. `sam local invoke` ejecuta la Lambda dentro de Docker, pasándole `events/s3-put.json`:
   un evento falso que imita el aviso de EventBridge y apunta a esa misma key.
3. `aws s3 ls` lista la carpeta para ver si apareció `processed.jpg` o `error.json`.
4. El último `aws s3 cp` (al revés) descarga el resultado a `out\` para verlo.

Antes del primer deploy no se dispara nada en AWS al subir la foto: la única ejecución es
la de `sam local invoke`.

**Desplegar.** SAM muestra los cambios y pide confirmación:

```powershell
sam deploy
```

**Probar en AWS.** Sube una foto a `tmp/<cualquier-id>/original.jpg` y, en unos segundos,
debe aparecer `processed.jpg` en la misma carpeta. Para ver los logs:

```powershell
sam logs -n ImageProcessorFunction --stack-name stockify-image-processor --profile stockify --tail
```

Para borrar todo lo desplegado: `sam delete`.
