Guia: Carregamento de Registros a partir do counter_dict
======================================================================

Propósito
----------------------------------------------------------------------

A tarefa ``task_load_records_from_counter_dict`` coleta documentos XML de uma
coleção específica do SciELO por meio do endpoint ``counter_dict`` da API do
OPAC e os carrega no sistema.

**O que ela faz:**

1. Conecta-se à API do OPAC (ex., ``https://www.scielo.br/api/v1/counter_dict``)
2. Obtém metadados dos documentos da coleção e intervalo de datas especificados
3. Para cada documento encontrado, despacha uma subtarefa
   (``task_load_record_from_xml_url``) que baixa o XML e cria ou atualiza
   registros em **PidProviderXML** e **XMLURL**

.. important::

   Esta tarefa **apenas** cria ou atualiza registros ``PidProviderXML`` e
   ``XMLURL``. Ela **não** cria registros de ``Article``.


Criação de uma Tarefa Periódica via Django Admin
----------------------------------------------------------------------

Passo 1: Acessar o Django Admin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Abra seu navegador e acesse o painel de administração do Django:
   ``https://<seu-dominio>/admin/``
2. Faça login com uma conta de superusuário

Passo 2: Navegar até Tarefas Periódicas
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Na barra lateral ou página principal do Django admin, localize a seção
   **PERIODIC TASKS** (fornecida pelo ``django_celery_beat``)
2. Clique em **Periodic tasks**
3. Clique no botão **Add periodic task** (canto superior direito)

Passo 3: Configurar a Tarefa
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Preencha os seguintes campos:

- **Name**: Um nome descritivo, ex.,
  ``Carregar registros OPAC - Brasil (scl)``
- **Task (registered)**: Selecione ou digite:
  ``pid_provider.tasks.task_load_records_from_counter_dict``
- **Enabled**: Marque esta caixa para ativar a tarefa
- **Schedule**: Escolha um dos tipos de agendamento disponíveis:

  - **Interval**: ex., a cada 24 horas
  - **Crontab**: ex., ``0 2 * * *`` (todos os dias às 2:00 AM)
  - **One-off task**: Marque esta opção se a tarefa deve executar apenas uma vez

Passo 4: Configurar os Argumentos de Palavra-Chave (kwargs)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No campo **Keyword arguments** (formato JSON), insira os parâmetros da tarefa:

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

Passo 5: Salvar
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Clique em **Save** para criar a tarefa periódica. O agendador Celery Beat irá
executá-la conforme o agendamento configurado.


Referência de Parâmetros
----------------------------------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 10 15 55

   * - Parâmetro
     - Tipo
     - Padrão
     - Descrição
   * - ``username``
     - str
     - ``None``
     - Nome do usuário que executa a tarefa
   * - ``user_id``
     - int
     - ``None``
     - ID do usuário (alternativa ao ``username``)
   * - ``collection_acron``
     - str
     - ``"scl"``
     - Acrônimo da coleção (ex., ``"scl"`` para Brasil)
   * - ``from_date``
     - str
     - ``"2000-01-01"``
     - Data inicial no formato ISO (``YYYY-MM-DD``)
   * - ``until_date``
     - str
     - hoje
     - Data final no formato ISO (``YYYY-MM-DD``)
   * - ``limit``
     - int
     - ``100``
     - Número de documentos por página da API
   * - ``timeout``
     - int
     - ``5``
     - Tempo limite da requisição HTTP em segundos
   * - ``force_update``
     - bool
     - ``false``
     - Forçar atualização mesmo se o registro já existir
   * - ``opac_domain``
     - str
     - ``"www.scielo.br"``
     - Domínio do OPAC de onde coletar


Verificação dos Resultados
----------------------------------------------------------------------

Após a conclusão da tarefa, verifique os resultados consultando os modelos
``PidProviderXML`` e ``XMLURL``.

Verificar Registros PidProviderXML
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No Django admin, navegue até **PID PROVIDER > PidProviderXML** para ver os
registros criados ou atualizados.

Alternativamente, utilize o shell do Django:

.. code-block:: python

   from pid_provider.models import PidProviderXML

   # Listar registros recentes
   recentes = PidProviderXML.objects.order_by("-updated")[:20]
   for registro in recentes:
       print(f"PID v3: {registro.v3} | Status: {registro.proc_status} | "
             f"Atualizado: {registro.updated}")

   # Filtrar por coleção
   from collection.models import Collection
   col = Collection.objects.get(acron="scl")
   registros = PidProviderXML.objects.filter(collections=col)
   print(f"Total de registros para 'scl': {registros.count()}")

Verificar Registros XMLURL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No Django admin, navegue até **PID PROVIDER > XMLURL** para ver o status de
processamento das URLs.

.. code-block:: python

   from pid_provider.models import XMLURL

   # Listar registros XMLURL recentes
   urls_recentes = XMLURL.objects.order_by("-updated")[:20]
   for url_registro in urls_recentes:
       print(f"URL: {url_registro.url} | Status: {url_registro.status} | "
             f"PID: {url_registro.pid}")

   # Verificar URLs com falha
   com_falha = XMLURL.objects.exclude(status="").exclude(exceptions="")
   print(f"URLs com erros: {com_falha.count()}")


Solução de Problemas
----------------------------------------------------------------------

.. _criticality-levels-pt:

Os problemas são categorizados por nível de criticidade:

- 🔴 **CRÍTICO** — Impede a execução da tarefa completamente; deve ser resolvido imediatamente
- 🟡 **MODERADO** — A tarefa executa, mas produz resultados incompletos ou incorretos
- 🟢 **BAIXO** — Problemas menores que não afetam a funcionalidade principal

.. list-table::
   :header-rows: 1
   :widths: 8 30 62

   * - Nível
     - Problema
     - Solução
   * - 🔴
     - O worker do Celery não está em execução
     - Inicie o worker do Celery: ``celery -A config worker -l info``. Sem um
       worker em execução, nenhuma tarefa será processada.
   * - 🔴
     - O agendador Celery Beat não está em execução
     - Inicie o Celery Beat: ``celery -A config beat -l info``. Sem o Beat, as
       tarefas periódicas não serão despachadas.
   * - 🔴
     - Falha na conexão com a API do OPAC (erro de rede/DNS)
     - Verifique se o ``opac_domain`` está acessível. Revise as regras de
       firewall e a resolução DNS. Consulte os registros de
       ``UnexpectedEvent`` para detalhes do erro.
   * - 🟡
     - Nenhum registro aparece após a execução da tarefa
     - Verifique se ``from_date`` e ``until_date`` cobrem um intervalo com
       documentos publicados. Confirme se ``collection_acron`` está correto.
       Revise os logs do worker do Celery para avisos.
   * - 🟡
     - Os registros existem mas não são atualizados
     - Defina ``force_update`` como ``true`` nos kwargs para forçar o
       reprocessamento de registros existentes.
   * - 🟡
     - Registros XMLURL mostram status de erro
     - Verifique o campo ``exceptions`` no ``XMLURL`` para detalhes. Causas
       comuns incluem URLs de XML inválidas ou erros temporários do servidor.
       Os registros serão reprocessados em execuções futuras.
   * - 🟢
     - A tarefa executa lentamente
     - Reduza o parâmetro ``limit`` para processar menos documentos por página,
       ou aumente ``timeout`` se a API do OPAC estiver lenta. Isso não afeta a
       correção dos dados.
   * - 🟢
     - Alguns documentos são ignorados com avisos
     - Documentos sem um ``journal_acronym`` válido são ignorados. Verifique os
       logs do worker do Celery para mensagens de ``WARNING``. Estes são
       tipicamente registros incompletos na API do OPAC.

Verificar Logs de Erros
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Os erros são registrados no modelo ``UnexpectedEvent``:

.. code-block:: python

   from tracker.models import UnexpectedEvent

   erros = UnexpectedEvent.objects.filter(
       detail__task="task_load_records_from_counter_dict"
   ).order_by("-created")[:10]

   for erro in erros:
       print(f"Data: {erro.created}")
       print(f"Exceção: {erro.exception}")
       print(f"Detalhes: {erro.detail}")
       print("---")
