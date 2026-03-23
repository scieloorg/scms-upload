Guía: Carga de Registros desde counter_dict
======================================================================

Propósito
----------------------------------------------------------------------

La tarea ``task_load_records_from_counter_dict`` recopila documentos XML de una
colección específica de SciELO a través del endpoint ``counter_dict`` de la API
del OPAC y los carga en el sistema.

**Qué hace:**

1. Se conecta a la API del OPAC (ej., ``https://www.scielo.br/api/v1/counter_dict``)
2. Obtiene metadatos de documentos de la colección y rango de fechas especificados
3. Para cada documento encontrado, despacha una subtarea
   (``task_load_record_from_xml_url``) que descarga el XML y crea o actualiza
   registros en **PidProviderXML** y **XMLURL**

.. important::

   Esta tarea **solo** crea o actualiza registros ``PidProviderXML`` y ``XMLURL``.
   **No** crea registros de ``Article``.


Creación de una Tarea Periódica vía Django Admin
----------------------------------------------------------------------

Paso 1: Acceder a Django Admin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Abra su navegador y navegue al panel de administración de Django:
   ``https://<su-dominio>/admin/``
2. Inicie sesión con una cuenta de superusuario

Paso 2: Navegar a Tareas Periódicas
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. En la barra lateral o página principal de Django admin, localice la
   sección **PERIODIC TASKS** (provista por ``django_celery_beat``)
2. Haga clic en **Periodic tasks**
3. Haga clic en el botón **Add periodic task** (esquina superior derecha)

Paso 3: Configurar la Tarea
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Complete los siguientes campos:

- **Name**: Un nombre descriptivo, ej.,
  ``Cargar registros OPAC - Brasil (scl)``
- **Task (registered)**: Seleccione o escriba:
  ``pid_provider.tasks.task_load_records_from_counter_dict``
- **Enabled**: Marque esta casilla para activar la tarea
- **Schedule**: Elija uno de los tipos de programación disponibles:

  - **Interval**: ej., cada 24 horas
  - **Crontab**: ej., ``0 2 * * *`` (todos los días a las 2:00 AM)
  - **One-off task**: Marque esta opción si la tarea debe ejecutarse solo una vez

Paso 4: Configurar los Argumentos de Palabra Clave (kwargs)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

En el campo **Keyword arguments** (formato JSON), ingrese los parámetros de la
tarea:

.. code-block:: json

   {
     "username": "admin",
     "collection_acron": "scl",
     "from_date": "2024-01-01",
     "until_date": "2024-12-31",
     "limit": 100,
     "timeout": 5,
     "force_update": false,
     "opac_domain": "www.scielo.br"
   }

Paso 5: Guardar
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Haga clic en **Save** para crear la tarea periódica. El programador Celery Beat
la ejecutará según la programación configurada.


Referencia de Parámetros
----------------------------------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 10 15 55

   * - Parámetro
     - Tipo
     - Predeterminado
     - Descripción
   * - ``username``
     - str
     - ``None``
     - Nombre de usuario que ejecuta la tarea
   * - ``user_id``
     - int
     - ``None``
     - ID de usuario (alternativa a ``username``)
   * - ``collection_acron``
     - str
     - ``"scl"``
     - Acrónimo de la colección (ej., ``"scl"`` para Brasil)
   * - ``from_date``
     - str
     - ``"2000-01-01"``
     - Fecha de inicio en formato ISO (``YYYY-MM-DD``)
   * - ``until_date``
     - str
     - hoy
     - Fecha final en formato ISO (``YYYY-MM-DD``)
   * - ``limit``
     - int
     - ``100``
     - Número de documentos por página de la API
   * - ``timeout``
     - int
     - ``5``
     - Tiempo de espera de la solicitud HTTP en segundos
   * - ``force_update``
     - bool
     - ``false``
     - Forzar la actualización aunque el registro ya exista
   * - ``opac_domain``
     - str
     - ``"www.scielo.br"``
     - Dominio del OPAC desde donde recopilar


Verificación de Resultados
----------------------------------------------------------------------

Después de que la tarea se complete, verifique los resultados comprobando los
modelos ``PidProviderXML`` y ``XMLURL``.

Verificar Registros PidProviderXML
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

En Django admin, navegue a **PID PROVIDER > PidProviderXML** para ver los
registros creados o actualizados.

Alternativamente, use el shell de Django:

.. code-block:: python

   from pid_provider.models import PidProviderXML

   # Listar registros recientes
   recientes = PidProviderXML.objects.order_by("-updated")[:20]
   for registro in recientes:
       print(f"PID v3: {registro.v3} | Estado: {registro.proc_status} | "
             f"Actualizado: {registro.updated}")

   # Filtrar por colección
   from collection.models import Collection
   col = Collection.objects.get(acron="scl")
   registros = PidProviderXML.objects.filter(collections=col)
   print(f"Total de registros para 'scl': {registros.count()}")

Verificar Registros XMLURL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

En Django admin, navegue a **PID PROVIDER > XMLURL** para ver el estado de
procesamiento de URLs.

.. code-block:: python

   from pid_provider.models import XMLURL

   # Listar registros XMLURL recientes
   urls_recientes = XMLURL.objects.order_by("-updated")[:20]
   for url_registro in urls_recientes:
       print(f"URL: {url_registro.url} | Estado: {url_registro.status} | "
             f"PID: {url_registro.pid}")

   # Verificar URLs fallidas
   fallidas = XMLURL.objects.exclude(status="").exclude(exceptions="")
   print(f"URLs con errores: {fallidas.count()}")


Solución de Problemas
----------------------------------------------------------------------

.. _criticality-levels-es:

Los problemas se categorizan por nivel de criticidad:

- 🔴 **CRÍTICO** — Impide la ejecución de la tarea por completo; debe resolverse inmediatamente
- 🟡 **MODERADO** — La tarea se ejecuta pero produce resultados incompletos o incorrectos
- 🟢 **BAJO** — Problemas menores que no afectan la funcionalidad principal

.. list-table::
   :header-rows: 1
   :widths: 8 30 62

   * - Nivel
     - Problema
     - Solución
   * - 🔴
     - El worker de Celery no está en ejecución
     - Inicie el worker de Celery: ``celery -A config worker -l info``. Sin un
       worker en ejecución, ninguna tarea será procesada.
   * - 🔴
     - El programador Celery Beat no está en ejecución
     - Inicie Celery Beat: ``celery -A config beat -l info``. Sin Beat, las
       tareas periódicas no serán despachadas.
   * - 🔴
     - La conexión a la API del OPAC falla (error de red/DNS)
     - Verifique que el ``opac_domain`` sea accesible. Revise las reglas de
       firewall y la resolución DNS. Consulte los registros de
       ``UnexpectedEvent`` para obtener detalles del error.
   * - 🟡
     - No aparecen registros después de la ejecución de la tarea
     - Verifique que ``from_date`` y ``until_date`` cubran un rango con
       documentos publicados. Confirme que ``collection_acron`` sea correcto.
       Revise los logs del worker de Celery para advertencias.
   * - 🟡
     - Los registros existen pero no se actualizan
     - Establezca ``force_update`` en ``true`` en los kwargs para forzar el
       reprocesamiento de registros existentes.
   * - 🟡
     - Los registros XMLURL muestran estado de error
     - Verifique el campo ``exceptions`` en ``XMLURL`` para obtener detalles.
       Las causas comunes incluyen URLs de XML inválidas o errores temporales
       del servidor. Los registros serán reintentados en ejecuciones futuras.
   * - 🟢
     - La tarea se ejecuta lentamente
     - Reduzca el parámetro ``limit`` para procesar menos documentos por
       página, o aumente ``timeout`` si la API del OPAC es lenta. Esto no
       afecta la corrección de los datos.
   * - 🟢
     - Algunos documentos se omiten con advertencias
     - Los documentos sin un ``journal_acronym`` válido se omiten. Revise los
       logs del worker de Celery para mensajes de ``WARNING``. Estos son
       típicamente registros incompletos en la API del OPAC.

Verificar Logs de Errores
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Los errores se registran en el modelo ``UnexpectedEvent``:

.. code-block:: python

   from tracker.models import UnexpectedEvent

   errores = UnexpectedEvent.objects.filter(
       detail__task="task_load_records_from_counter_dict"
   ).order_by("-created")[:10]

   for error in errores:
       print(f"Fecha: {error.created}")
       print(f"Excepción: {error.exception}")
       print(f"Detalles: {error.detail}")
       print("---")
