# SCMS Upload — Versão 3.x

> Insumos para a documentação técnica da versão **3.x** do `scms-upload`.
> Conteúdo elaborado a partir do branch [`rc`](https://github.com/scieloorg/scms-upload/tree/rc) (versão de referência `v3.0.0rc20`).

---

## 1. Propósito da versão 3.x

A versão 3.x do **SCMS Upload** consolida o sistema como **plataforma única
de ingresso de conteúdo SciELO**. Ela mantém todo o aparato de migração e
publicação herdado da 2.x e **incorpora, como cidadão de primeira classe, o
fluxo de envio de pacotes SPS por produtores de XML / equipes editoriais**,
com QA assistido por *checklist*.

Os objetivos centrais da 3.x são:

- **Receber pacotes SPS** (ZIP) enviados por usuários autenticados (produtores
  de XML, equipes editoriais), individualmente ou em lote (`PackageZip`).
- **Validar automaticamente** estrutura, conteúdo, ativos (figuras),
  *renditions* (PDFs) e a renderização final do artigo.
- **Orquestrar o fluxo de QA** — aprovação, devolução para correção,
  pré-visualização, publicação e gestão de erratas/atualizações — com
  estados bem definidos.
- **Reaproveitar** todo o pipeline de PIDs, empacotamento SPS, publicação no
  site novo e rastreabilidade já existente na 2.x.
- **Continuar suportando a migração** do site clássico (modo de operação
  herdado), permitindo coexistência dos dois fluxos na mesma instalação.

> Diferença chave em relação à 2.x: o app `upload` **está habilitado** em
> `INSTALLED_APPS` e o menu Wagtail expõe explicitamente as entradas
> `upload` e `upload-error`.

---

## 2. Arquitetura geral

A 3.x mantém a mesma arquitetura **Django + Wagtail + Celery + Redis +
PostgreSQL + MinIO** da 2.x. As mudanças relevantes são funcionais (escopo
do app `upload`) e de versionamento de dependências.

### 2.1 Stack tecnológica

| Camada | Tecnologia | Versão / Observações (3.x) |
| --- | --- | --- |
| Linguagem | Python | 3.x |
| Framework web | Django | 5.2.3 |
| CMS | Wagtail | (admin para gestão de conteúdo) |
| Tarefas assíncronas | Celery | 5.5.3 (com `django-celery-beat` 2.8.1) |
| Broker / cache | Redis | 5.x |
| Banco de dados | PostgreSQL | (via `django-environ`) |
| Object storage | MinIO / S3 | usado por `files_storage` |
| API | Django REST Framework | 3.15.x + JWT |
| Bibliotecas SciELO | `packtools` `4.14.4`, `scielo_classic_website` `1.10.6` | dependências instaladas via `git+https` |
| Empacotamento | Docker + `docker-compose` | `local.yml`, `production-v3.0.0rc4.yml` |

> Em relação à 2.x: a 3.x usa **versões anteriores** de `packtools` e
> `scielo_classic_website`. Isso reflete o ciclo de release das duas linhas
> (a 3.x foi cortada antes das atualizações que entraram na 2.x mais
> recente). Verifique compatibilidade ao realizar *backports*.

### 2.2 Containers (compose)

Idênticos à 2.x: `django`, `celeryworker`, `celerybeat`, `flower`,
`postgres`, `redis`, `minio`, `docs`. O arquivo de produção de referência
nesta linha é `production-v3.0.0rc4.yml`.

### 2.3 Modelo de execução

Mesmo padrão da 2.x (tarefas Celery acionadas por UI/API/beat com *fan-out*
por coleção/periódico/fascículo/artigo). A novidade é o ramo dedicado a
pacotes enviados por usuário, descrito em §4.1.

---

## 3. Componentes (apps Django)

A relação a seguir reflete `LOCAL_APPS` em `config/settings/base.py` no
branch `rc`. Todos os apps da 2.x continuam presentes; o destaque é o
`upload` ativado.

| App | Responsabilidade principal | Mudança vs. 2.x |
| --- | --- | --- |
| `core` | Tipos e utilitários compartilhados (`CommonControlField`, sanitização, profiling, requisições, arquivos). | — |
| `core_settings` | Configurações via Wagtail snippets. | — |
| `collection` | `Collection`, `Language`, `WebSiteConfiguration`/`WebSiteConfigurationEndpoint`. | — |
| `journal` | Periódicos (`Journal`, `OfficialJournal`, `JournalSection`). | — |
| `issue` | Fascículos (`Issue`, `TOC`, `TocSection`). | — |
| `article` | Artigos (modelo enxuto; fonte de verdade é o XML). | — |
| `migration` | Migração do *classic website* (mantém `MigratedJournal/Issue/Article/File`, `ClassicWebsiteConfiguration`). | Pequenos ajustes (ex.: `migrate_journal`/`migrate_issue` inicializam `detail` como `dict` vazio). |
| `htmlxml` | Conversão HTML→XML SciELO PS. | Ajustes para tratar duplicatas em `HTMLXML.get()` / `create_or_update()` (`MultipleObjectsReturned`). |
| `package` | Pacotes SPS (`SPSPkg`), `PkgZipBuilder`, integração com `files_storage`. | Tratamento de `pkg_name` ausente em `fix_pkg_name` (evita `KeyError`). |
| `pid_provider` | Provedor de PIDs `v2`/`v3`, deduplicação, reconciliação. | — |
| `proc` | `JournalProc`, `IssueProc`, `ArticleProc` (subclasses de `BaseProc`). | — |
| `publication` | Publicação no site novo via APIs REST. | `PublicationAPI` recebe parâmetro `enabled`; `publish_article_on_website` ganhou tratamento de exceção dedicado; correção do fluxo de autenticação/validação em `PublicationAPI`. |
| `tracker` | Eventos, relatórios, status de progresso (`PROGRESS_STATUS_*`). | `Operation.start` e `Operation.exclude_events` refatorados. |
| `files_storage` | MinIO/S3. | — |
| `doi` | DOIs por idioma. | — |
| `institution`, `location`, `researcher`, `team` | Entidades de apoio. | — |
| `bigbang` | Bootstrap inicial. | — |
| **`upload`** | **Recebimento e QA de pacotes SPS submetidos por usuários.** Modelos `Package`, `PackageZip`, `ValidationReport`, `UploadValidator`. Pipeline próprio em `upload/tasks.py`. | **Habilitado** em `INSTALLED_APPS` (na 2.x estava comentado). |

### 3.1 App `upload` (núcleo da 3.x)

O `upload` é o que diferencia esta linha de versões. Ele oferece um
**caminho paralelo ao da migração** para que pacotes SPS cheguem ao mesmo
pipeline de pacotes, PIDs e publicação.

Modelos principais:

- **`PackageZip`** — agrupa um conjunto de pacotes enviados juntos
  (submissão em lote).
- **`Package`** — representa um pacote SPS individual (um artigo). Mantém
  status do fluxo (ver §3.2), referência ao XML/ZIP em `files_storage` e
  vínculos com `Article`, `Journal`, `Issue`.
- **`ValidationReport`** — relatórios produzidos pelas validações (estrutura,
  conteúdo, ativos, *renditions*, página renderizada).
- **`UploadValidator`** — configuração/critérios aplicáveis às validações
  (vide `validation_criteria_example.json` na raiz do repositório).

Tarefas Celery em `upload/tasks.py` (priority 0):

- `task_optimise_package(file_path)` — pré-processamento do ZIP recebido.
- `task_receive_packages(user_id, pkg_zip_id)` / `task_receive_package(user_id, pkg_id)` —
  ingestão de lote / individual.
- `task_validate_xml_structure(...)` — valida o XML usando
  `packtools.sps.validation.xml_structure.StructureValidator`.
- `task_validate_xml_content(...)` — valida o conteúdo do XML
  (`upload.validation.xml_data_checker.XMLDataChecker`).
- `task_validate_assets(package_id, xml_path, package_files, xml_assets)` —
  valida figuras/ativos.
- `task_validate_renditions(...)` / `task_validate_renditions_content(...)` —
  valida PDFs e seu conteúdo (`upload.validation.rendition_validation`).
- `task_validate_webpages_content(package_id)` — valida páginas renderizadas
  (`upload.validation.html_validation.validate_webpage`).
- `task_publish_article(...)` — publica o artigo aprovado.
- `task_complete_journal_data(...)` / `task_complete_issue_data(...)` —
  preenche metadados de periódico/fascículo a partir do pacote.

A controller `upload.controller.receive_package` orquestra a recepção; o
`proc.controller` continua sendo o ponto de entrada para garantir que
`JournalProc` e `IssueProc` existam (`ensure_journal_proc_exists`,
`ensure_issue_proc_exists`).

### 3.2 Estados do `Package` (fluxo de QA)

`upload/choices.py` documenta o fluxo (resumo):

```
1. PS_SUBMITTED            → primeira avaliação automática
2. PS_ENQUEUED_FOR_VALIDATION
   ├─ PS_READY_TO_PREVIEW          (sem erros bloqueantes)
   ├─ PS_PENDING_CORRECTION        (erros que exigem correção)
   ├─ PS_VALIDATED_WITH_ERRORS     (erros toleráveis → decisão QA)
   └─ PS_UNEXPECTED                (falha inesperada)
3. QA decide:
   ├─ PS_PUBLISHED                 (aprovação imediata em casos diretos)
   ├─ PS_PENDING_QA_DECISION       (gargalo da unidade SciELO; mais tolerante)
   ├─ PS_REQUIRED_ERRATUM          (publicar errata)
   └─ PS_REQUIRED_UPDATE           (atualização do artigo)
4. Pré-visualização:
   PS_READY_TO_PREVIEW → PS_PREVIEW → PS_READY_TO_PUBLISH → PS_PUBLISHED
5. Outros: PS_DEPUBLISHED, PS_ARCHIVED
```

Constantes correspondentes (`PS_*`):
`submitted`, `enqueued-for-validation`, `validated-with-errors`,
`pending-correction`, `pending-qa-decision`, `unexpected`,
`ready-to-preview`, `preview`, `ready-to-publish`, `published`,
`required-erratum`, `required-update`, `depublished`, `archived`.

### 3.3 Camadas reutilizadas da 2.x

`pid_provider`, `proc`, `package`, `publication`, `tracker`, `files_storage`
e `migration` mantêm **a mesma arquitetura e contratos** descritos em
[`docs/v2.x/README.md`](../v2.x/README.md). Mudanças pontuais foram
listadas na tabela acima e refletem correções de robustez aplicadas na
linha 3.x.

---

## 4. Funcionalidades

### 4.1 Recepção e QA de pacotes SPS (novidade da 3.x)

1. **Submissão** — usuário autenticado envia um ZIP (individual ou lote) via
   admin Wagtail / API. Os arquivos são persistidos em `files_storage`
   (MinIO) e cria-se `Package` (e `PackageZip` quando em lote).
2. **Otimização** — `task_optimise_package` normaliza/recompacta o ZIP.
3. **Recepção** — `task_receive_packages` itera sobre o lote e dispara
   `task_receive_package` por pacote, garantindo que `JournalProc` e
   `IssueProc` existam.
4. **Validações em paralelo** (todas com prioridade 0):
   - Estrutura XML (`StructureValidator`).
   - Conteúdo XML (`XMLDataChecker`).
   - Ativos (figuras) e *renditions* (PDFs).
   - Conteúdo das *renditions* e da página renderizada.
5. **Relatórios** — cada validação produz `ValidationReport`s navegáveis
   via Wagtail.
6. **Decisão de QA** — operador transiciona o `Package` entre os estados
   descritos em §3.2 (`pending-correction`, `ready-to-preview`,
   `ready-to-publish`, `published`, etc.).
7. **Pré-visualização e publicação** — `task_publish_article` envia o
   artigo aprovado ao site novo via `publication.api.document`. A
   verificação posterior de disponibilidade é feita por
   `publication.tasks.task_check_article_availability`.
8. **Errata / Atualização** — estados `PS_REQUIRED_ERRATUM` e
   `PS_REQUIRED_UPDATE` permitem ao QA exigir uma nova submissão
   vinculada (errata) ou atualização do artigo já publicado.

### 4.2 Migração do site clássico (mantida)

Idêntico à 2.x — `proc/tasks.py` mantém `task_migrate_and_publish_*` para
periódicos, fascículos e artigos, e `migration` continua como ponto de
entrada do *classic website*.

### 4.3 PID Provider

Mesmo escopo da 2.x: emissão e reconciliação de `pid_v2`/`pid_v3`,
deduplicação, correções em lote (`task_fix_pid_v2`), endpoints REST e
tarefas de carga (`task_load_records_*`).

### 4.4 Publicação no site novo

Clientes em `publication/api/`. Na 3.x, `PublicationAPI`:

- aceita parâmetro `enabled` para habilitar/desabilitar dinamicamente um
  endpoint de publicação;
- teve o fluxo de autenticação e validação corrigido;
- `publish_article_on_website` faz tratamento explícito de exceção,
  evitando que falhas de um artigo derrubem o lote.

`ArticleAvailability` continua registrando disponibilidade do artigo no
site novo e antigo.

### 4.5 Observabilidade e auditoria

- `tracker.UnexpectedEvent.create(e, exc_traceback, detail=...)` é o padrão
  para registrar exceções com contexto estruturado.
- Sanitização de `detail`/JSON: tentar `json.dumps`; em falha, aplicar
  `core.utils.sanitize.sanitize_for_json` (sanitiza apenas
  `str/dict/list/tuple` e devolve outros tipos inalterados).
- `Operation.start` e `Operation.exclude_events` foram refatorados na 3.x.
- Tratamento de `MultipleObjectsReturned` em `HTMLXML.get()` /
  `create_or_update()` foi adicionado para lidar com duplicatas históricas.

### 4.6 API REST e autenticação

DRF + `djangorestframework-simplejwt`. Os endpoints expostos por
`pid_provider` e `collection` permanecem; o app `upload` adiciona seu
próprio conjunto (gestão de pacotes, validações e relatórios).

### 4.7 Painel administrativo (Wagtail)

`config/menu.py` na 3.x contempla, em ordem, as entradas:

```
None, "unexpected-error", "Tasks", "processing", "migration",
"journal", "issue", "article", "institution", "location", "researcher",
"collection", "pid_provider", "upload", "upload-error", "Configurações",
"Relatórios", "Images", "Documentos", "Ajuda"
```

Note as entradas exclusivas da 3.x: **`upload`** e **`upload-error`**.

---

## 5. Estrutura de diretórios (alto nível)

```
scms-upload/  (branch rc, v3.x)
├── article/             # Modelo Article + relacionados
├── bigbang/             # Bootstrap inicial do sistema
├── collection/          # Coleções SciELO e configuração de site
├── compose/             # Dockerfiles e scripts dev/prod
├── config/              # Settings Django, Celery, URLs, menu Wagtail
├── core/                # Tipos e utilitários comuns
├── core_settings/
├── django_celery_beat/
├── docs/                # Documentação Sphinx
│   └── v3.x/            # ← este documento
├── doi/
├── files_storage/       # MinIO/S3
├── htmlxml/             # Conversão HTML→XML
├── institution/
├── issue/
├── journal/
├── libs/
├── locale/
├── location/
├── migration/           # Migração do classic website
├── package/             # Pacotes SPS
├── pid_provider/        # Provedor de PIDs
├── proc/                # JournalProc / IssueProc / ArticleProc
├── publication/         # Publicação no site novo
├── researcher/
├── requirements/        # Pinned dependencies
├── team/
├── tracker/             # Eventos, relatórios, status de progresso
├── upload/              # ← ATIVO na 3.x: recepção e QA de pacotes SPS
│   ├── controller.py    # receive_package(...)
│   ├── models.py        # Package, PackageZip, ValidationReport, UploadValidator
│   ├── tasks.py         # task_receive_*, task_validate_*, task_publish_article, ...
│   ├── publication.py
│   ├── validation/
│   │   ├── xml_data_checker.py
│   │   ├── rendition_validation.py
│   │   └── html_validation.py
│   └── utils/{file_utils,package_utils,xml_utils}.py
├── validation_criteria_example.json
├── local.yml            # docker-compose desenvolvimento
├── production-v3.0.0rc4.yml
├── manage.py
└── README.md
```

---

## 6. Como executar (desenvolvimento)

Resumo do `Makefile` (idêntico à 2.x):

```bash
make build compose=local.yml   # build da stack local
make up                        # subir containers
make django_migrate            # aplicar migrações
make django_createsuperuser    # criar usuário admin
make django_test               # rodar testes
make stop                      # parar containers
```

---

## 7. Convenções importantes

São as mesmas da 2.x (e devem ser preservadas em qualquer evolução da 3.x):

- **`CommonControlField`** em modelos relevantes para auditoria automática.
- **Sanitização de `detail`/JSON**: `json.dumps` → fallback para
  `core.utils.sanitize.sanitize_for_json`.
- **`BaseProc.get_or_create`** trata `MultipleObjectsReturned` removendo
  duplicatas (não há *unique constraint* em `(collection, pid)`).
- **`proc/controller.py`** é fachada de compatibilidade; a superfície
  pública é definida em `__all__`.
- **ViewSets Wagtail** devem estender `core.views.CommonControlFieldViewSet`
  para preencher `creator`/`updated_by` automaticamente a partir de
  `request.user`.
- **Critérios de validação** do app `upload` são parametrizados via
  `UploadValidator` (ver `validation_criteria_example.json`).

---

## 8. Diferenças resumidas vs. 2.x

| Aspecto | 2.x (`main`, `v2.12.0rc6`) | 3.x (`rc`, `v3.0.0rc20`) |
| --- | --- | --- |
| App `upload` | Presente, **desabilitado** em `INSTALLED_APPS` | **Habilitado**, é o diferencial da linha |
| Menu Wagtail | Inicia em `"Tarefas"`; sem entradas de upload | Inclui `"upload"` e `"upload-error"`; pequena reordenação |
| `packtools` | `4.16.1` | `4.14.4` |
| `scielo_classic_website` | `1.10.7` | `1.10.6` |
| Compose de produção | `production.yml` | `production-v3.0.0rc4.yml` |
| Guias `docs/pid_provider/` e `docs/processing/` | Presentes | Não estão presentes neste branch |
| Pipeline de migração | Caminho principal | Mantido, coexiste com o pipeline de upload |
| `PublicationAPI` | Versão anterior | `enabled` flag, fluxo de auth/validação revisto, exceção tratada em `publish_article_on_website` |
| `Operation.start` / `exclude_events` | Implementação anterior | Refatorados |
| `HTMLXML` | Implementação anterior | Trata `MultipleObjectsReturned` em `get()` / `create_or_update()` |

---

## 9. Documentos relacionados

- Documentação da linha anterior: [`docs/v2.x/README.md`](../v2.x/README.md).
- Documentação Sphinx geral: [`docs/index.rst`](../index.rst).
- Critérios de validação de upload: `validation_criteria_example.json`
  (na raiz do repositório).

---

## 10. Versão de referência

Este documento foi escrito a partir do estado do branch `rc` em
`v3.0.0rc20`. Nomes de tarefas, status do `Package` e contratos de API
podem evoluir; sempre confronte com o código atual antes de implementar
sobre estes insumos.
