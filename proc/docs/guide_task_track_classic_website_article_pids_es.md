# Guía: task_track_classic_website_article_pids

## Propósito

La tarea `proc.tasks.task_track_classic_website_article_pids` compara los PIDs de
artículos registrados en el sitio web clásico de SciELO (leídos desde un archivo
de texto indicado en `ClassicWebsiteConfiguration.pid_list_path`) con los registros
`ArticleProc` ya almacenados en el sistema. A continuación, actualiza el campo
`pid_status` de cada registro:

| Estado | Significado |
|---|---|
| **matched** | El PID existe tanto en el sitio web clásico como en `ArticleProc` con `migrated_data` vinculado. |
| **missing** | El PID existe en `ArticleProc` pero no tiene `migrated_data` vinculado. |
| **exceeding** | El PID está presente en `ArticleProc` pero no fue encontrado en la lista de PIDs del sitio web clásico. |

Los PIDs nuevos encontrados en el archivo del sitio web clásico que aún no tienen
un registro `ArticleProc` correspondiente se crean automáticamente con estado
**missing**.

### Prerrequisitos

| Requisito | Detalles |
|---|---|
| **Configuración del sitio web clásico** | Debe existir un registro `ClassicWebsiteConfiguration` para la colección de destino, con un `pid_list_path` válido que apunte a un archivo de texto que contenga un PID por línea. |
| **Colección** | Debe existir al menos un registro `Collection`. |
| **Usuario** | Un usuario Django válido (por `username` o `user_id`). |

---

## Cómo crear la tarea periódica (django_celery_beat)

### Paso 1 – Acceder al panel de administración

1. Inicie sesión en el panel de administración de Wagtail (por ejemplo, `https://<su-dominio>/admin/`).
2. En el menú lateral izquierdo, vaya a **Settings > Periodic tasks**.

> Si no ve este elemento del menú, asegúrese de que la aplicación
> `django_celery_beat` esté instalada y de que su usuario tenga los
> permisos apropiados.

### Paso 2 – Crear una nueva tarea periódica

1. Haga clic en **Add periodic task**.
2. Complete los campos obligatorios:

| Campo | Valor |
|---|---|
| **Name** | Un nombre descriptivo, por ejemplo `Track Classic Website PIDs (scl)` |
| **Task (registered)** | Seleccione `proc.tasks.task_track_classic_website_article_pids` |
| **Enabled** | ✅ Marcado |

3. Elija una programación. Por ejemplo, para ejecutar una vez al día, cree o
   seleccione un **Interval Schedule** de `1 day` o un **Crontab Schedule**
   como `0 3 * * *` (todos los días a las 03:00).

### Paso 3 – Configurar los argumentos por palabra clave (kwargs)

En el campo **Keyword arguments (JSON)**, ingrese un objeto JSON con los
parámetros que acepta la tarea:

```json
{
  "username": "admin",
  "collection_acron": "scl"
}
```

#### Parámetros disponibles

| Parámetro | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `username` | string | **sí** | Nombre de usuario del usuario Django que se registrará como creador de cualquier nuevo registro `ArticleProc`. |
| `user_id` | integer | no | Alternativa a `username`. Si se proporcionan ambos, `user_id` tiene prioridad. |
| `collection_acron` | string | no | Acrónimo de la colección a procesar (por ejemplo, `"scl"` para Brasil). Si se omite, se procesan **todas** las colecciones. |

> **⚠️ Crítico:** El `username` o `user_id` debe corresponder a un usuario
> existente. Si el usuario no se encuentra, la tarea registrará un error y
> omitirá el procesamiento.

> **⚠️ Crítico:** Debe existir un registro `ClassicWebsiteConfiguration` con un
> `pid_list_path` válido para la colección de destino. Si la configuración
> no existe o el archivo no se puede leer, la tarea fallará para esa
> colección.

### Paso 4 – Guardar

Haga clic en **Save**. La tarea será recogida por el programador Celery Beat
de acuerdo con la programación que configuró.

---

## Verificación del resultado

### 1. Task Tracker (panel de administración de Wagtail)

En la barra lateral del panel de administración de Wagtail, vaya a
**Task Tracker** (en la sección Tracker). Busque entradas con el nombre
`proc.tasks.task_track_classic_website_article_pids`. Cada entrada muestra:

- **Item** – El acrónimo de la colección procesada (o `all`).
- **Status** – `started`, `completed` o `failed`.
- **Detail** – Un objeto JSON que contiene:
  - `params`: los kwargs utilizados.
  - `events`: una lista con los conteos de estado de PID por colección (por
    ejemplo, `{"collection": "scl", "matched": 1200, "missing": 50,
    "exceeding": 3}`).
  - `exceptions`: cualquier error que haya ocurrido.

### 2. Registros ArticleProc (panel de administración de Wagtail)

Navegue a la lista de **ArticleProc** en el panel de administración y filtre
por `pid_status` para verificar la distribución:

- **matched** – artículos vinculados exitosamente.
- **missing** – artículos que necesitan atención (sin `migrated_data`).
- **exceeding** – artículos en el sistema pero no en la lista de PIDs del
  sitio web clásico.

### 3. Django shell / verificación programática

```python
from proc.models import ArticleProc
from django.db.models import Count

# Resumen de pid_status para una colección
ArticleProc.objects.filter(
    collection__acron="scl"
).values("pid_status").annotate(total=Count("pid")).order_by("pid_status")
```

### 4. Logs del worker de Celery

Revise la salida del worker de Celery para mensajes INFO y ERROR relacionados
con `task_track_classic_website_article_pids`. Los errores también se registran
en el modelo `UnexpectedEvent`, accesible desde el panel de administración de
Wagtail.
