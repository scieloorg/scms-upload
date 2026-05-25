# SCMS Upload — Versão 2.x

> Insumos para a documentação técnica da versão **2.x** do `scms-upload`.
> Conteúdo elaborado a partir do branch [`main`](https://github.com/scieloorg/scms-upload/tree/main) (versão de referência `v2.12.0rc6`).

---

## 1. Propósito da versão 2.x

A versão 2.x do **SCMS Upload** (SciELO Content Management System — Upload) é a
plataforma da SciELO responsável por **migrar, organizar e publicar o acervo
histórico** mantido nos sites clássicos da rede SciELO em direção ao novo
ecossistema de publicação. Nesta linha de versões, o foco é a **migração e
republicação** do conteúdo legado.

Os principais objetivos da 2.x são:

- **Importar** dados de periódicos, fascículos e artigos do *classic website*
  (base ISIS / file system) e materializá-los no modelo de dados do novo SCMS.
- **Padronizar e enriquecer** o XML SciELO PS dos artigos migrados, gerando
  pacotes SPS conformes (`SPSPkg`).
- **Atribuir e reconciliar** identificadores persistentes (PIDs `v2` e `v3`)
  através do *PID Provider*, garantindo continuidade entre o site clássico e o
  novo site.
- **Publicar** periódicos, fascículos e artigos nos serviços de publicação do
  novo site SciELO via APIs REST.
- **Rastrear** o estado de cada item migrado e o resultado de cada tarefa
  (eventos, erros e relatórios), permitindo reprocessar de forma seletiva.

> Observação: nesta linha de versões o app de **upload de pacotes SPS por
> usuários externos** (`upload`) está presente no código mas
> **desabilitado** em `INSTALLED_APPS`. O caso de uso "produtor de XML envia um
> pacote para QA" é foco da linha 3.x.

---

## 2. Arquitetura geral

O SCMS Upload é uma aplicação **Django + Wagtail** distribuída em containers e
orquestrada com **Celery** para processamento assíncrono.

### 2.1 Stack tecnológica

| Camada | Tecnologia | Versão / Observações (2.x) |
| --- | --- | --- |
| Linguagem | Python | 3.x |
| Framework web | Django | 5.2.3 |
| CMS | Wagtail | (admin para gestão de conteúdo) |
| Tarefas assíncronas | Celery | 5.5.3 (com `django-celery-beat` 2.8.1) |
| Broker / cache | Redis | 5.x |
| Banco de dados | PostgreSQL | (via `django-environ`) |
| Object storage | MinIO / S3 | usado por `files_storage` |
| API | Django REST Framework | 3.15.x + JWT |
| Bibliotecas SciELO | `packtools` `4.16.1`, `scielo_classic_website` `1.10.7` | dependências instaladas via `git+https` |
| Empacotamento | Docker + `docker-compose` | `local.yml`, `production.yml` |

### 2.2 Containers (compose)

A stack de desenvolvimento (`local.yml`) sobe, no mínimo:

- `django` — aplicação web (Wagtail + Django).
- `celeryworker` — workers Celery para tarefas assíncronas.
- `celerybeat` — agendador de tarefas periódicas (`django-celery-beat`).
- `flower` — painel de monitoramento Celery.
- `postgres` — banco relacional.
- `redis` — broker e backend de cache/resultados.
- `minio` — armazenamento de arquivos (XML, PDF, ativos, ZIPs).
- `docs` — servidor Sphinx para documentação.

### 2.3 Modelo de execução

1. O usuário (ou um *beat* agendado) dispara uma tarefa Celery a partir da
   interface Wagtail ou via API.
2. A tarefa orquestra subtarefas (frequentemente em *fan-out*: por coleção,
   por periódico, por fascículo, por artigo).
3. Cada subtarefa atualiza modelos de processo (`*Proc`), gera eventos
   (`tracker`) e, ao final, marca o item como pronto para publicação.
4. Tarefas de publicação enviam o conteúdo a APIs externas (site novo /
   *publication API*).

---

## 3. Componentes (apps Django)

A versão 2.x está organizada em **apps** Django/Wagtail. Cada app encapsula um
domínio do problema. A relação a seguir reflete `LOCAL_APPS` em
`config/settings/base.py` no branch `main`.

| App | Responsabilidade principal |
| --- | --- |
| `core` | Tipos e utilitários compartilhados: `CommonControlField` (auditoria de criação/edição), formulários base, helpers de sanitização (`core.utils.sanitize`), profiling, requisições HTTP, manipulação de arquivos. |
| `core_settings` | Configurações administráveis pela UI (Wagtail snippets). |
| `collection` | Modelo `Collection` (acervo SciELO por país/tema), `Language` e `WebSiteConfiguration`/`WebSiteConfigurationEndpoint` para apontar para os sites novo e clássico. |
| `journal` | Periódicos (`Journal`, `OfficialJournal`, `JournalSection`) com metadados editoriais. |
| `issue` | Fascículos (`Issue`, `TOC`, `TocSection`). |
| `article` | Artigos no contexto de Upload — modelo enxuto com PIDs, status, relações (`RelatedItem`, `ArticleAuthor`, DOI por idioma). Mantém o mínimo necessário porque a fonte de verdade é o XML. |
| `migration` | **Coração da 2.x.** Modelos `MigratedJournal`, `MigratedIssue`, `MigratedArticle`, `MigratedFile`, `ClassicWebsiteConfiguration`. Importa do *classic website* via `scielo_classic_website` e materializa registros no novo modelo. Também controla o status de migração por item (`MS_TO_MIGRATE` → `MS_IMPORTED` → `MS_PUBLISHED`). |
| `htmlxml` | Conversão e tratamento de HTML legado em XML SciELO PS. |
| `package` | Pacotes SPS (`SPSPkg`), montagem/extração de ZIPs, `PkgZipBuilder`, vínculo com `files_storage`. |
| `pid_provider` | Provedor de PIDs `v2` e `v3` para artigos. Modelo `PidProviderXML` com fluxos de reconciliação, deduplicação e correção (`PPXML_STATUS_*`). Endpoints REST e tarefas Celery (`provide_pid_for_file`, `task_fix_pid_v2`, etc.). |
| `proc` | **Camada de processo.** Modelos `JournalProc`, `IssueProc`, `ArticleProc` (subclasses de `BaseProc`) que rastreiam, por coleção, o ciclo de vida da migração e publicação. `proc/controller.py` é fachada de compatibilidade que reexporta a API pública via `__all__`. |
| `publication` | Publicação no site novo. `publication.api.*` define clientes para Document/Issue/Journal/PressRelease. Modelo `ArticleAvailability` registra disponibilidade do artigo no site novo e antigo. |
| `tracker` | Auditoria de execução: `Event`, `EventReport`, `UnexpectedEvent`, `OperationProc`. Padrão `PROGRESS_STATUS_*` (`TODO`, `DOING`, `DONE`, `BLOCKED`, `PENDING`, `IGNORED`, `REPROC`). Estratégia de sanitização: ao salvar `detail`/JSON tenta `json.dumps`; em falha aplica `sanitize_for_json` para remover *surrogates*. |
| `files_storage` | Integração com MinIO/S3: `FileLocation`, `MinioConfiguration`. |
| `doi` | Modelo `DOIWithLang`. |
| `institution` | Instituições. |
| `location` | Países, estados, cidades. |
| `researcher` | Pesquisadores/autores. |
| `team` | Equipe / responsáveis. |
| `bigbang` | *Bootstrap* do sistema (cargas iniciais). Veja `bigbang/scripts/start.py`. |
| `upload` | **Presente no código mas desabilitado** em `INSTALLED_APPS` na 2.x. Reservado para o fluxo de submissão por produtores de XML (foco da 3.x). |

### 3.1 Camada `proc/*Proc`

Os modelos `JournalProc`, `IssueProc` e `ArticleProc` representam o **estado
de processo** de cada entidade dentro de uma `Collection`:

- Herdam de `BaseProc`, que oferece `get_or_create` resiliente: se houver
  duplicatas `(collection, pid)` (não há *unique constraint* no banco), mantém
  a linha mais recente e remove as demais.
- Cada `*Proc` mantém `migration_status`, `pid_status` e referências aos
  artefatos gerados (XML, pacote SPS, eventos).
- A interface pública (controllers) é exportada por `proc/controller.py`
  através de `__all__`.

### 3.2 PID Provider

O `pid_provider` é o serviço autoritativo para emissão e reconciliação de
PIDs SciELO:

- Estados em `PPXML_STATUS`: `TODO`, `DONE`, `WAIT`, `IGNORE`, `UNDEF`,
  `NVALID`, `DUP`, `DEDUP`.
- Expõe tarefas para carga em massa (`task_load_records_from_counter_dict`,
  `task_load_record_from_xml_url`) e correção (`task_fix_pid_v2`).
- Há guias passo-a-passo em
  [`docs/pid_provider/`](../pid_provider/) (EN/ES/PT-BR).

### 3.3 Tracker

O `tracker` consolida a observabilidade do sistema. Cada operação relevante
gera registros que ficam navegáveis pelo admin Wagtail e podem ser exportados
em relatórios. Os estados de progresso seguem o conjunto
`PROGRESS_STATUS_*` listado em `tracker/choices.py`.

---

## 4. Funcionalidades

### 4.1 Migração do site clássico

Pipeline conduzido pelo app `migration` em conjunto com `proc`:

1. **Configuração de `ClassicWebsiteConfiguration`** com os caminhos das bases
   ISIS, do *file system* e do `pid_list_path`.
2. **Carga de PIDs** — `ClassicWebsiteConfiguration.get_pid_list` lê
   `pid_list_path` e devolve o conjunto de PIDs de artigos a migrar (ou
   conjunto vazio em erro).
3. **Importação** — `task_migrate_and_publish_*` (em `proc/tasks.py`):
   - `task_migrate_and_publish_journals[_by_collection]`
   - `task_migrate_and_publish_issues[_by_collection]`
   - `task_migrate_and_publish_articles[_by_journal|_by_issue]`
4. **Geração de pacotes SPS** — `package.PkgZipBuilder` monta o ZIP do
   artigo a partir dos arquivos migrados.
5. **Atribuição de PIDs** — chama o `pid_provider` para gerar/reconciliar
   `pid_v2` / `pid_v3`.
6. **Publicação** — `task_publish_journal`, `task_publish_issue`,
   `task_publish_article`, `task_sync_issue` enviam para a *publication API*.

### 4.2 Tratamento de HTML legado (`htmlxml`)

Converte HTML do site clássico em XML SciELO PS, alimentando o pipeline de
empacotamento.

### 4.3 Gestão de pacotes SPS (`package`)

- Modelo `SPSPkg` referencia o ZIP final, ativos, *renditions* e XML.
- `PkgZipBuilder` reúne XML, ativos (imagens) e PDFs em um único ZIP `SPS`.
- Integração com `files_storage` (MinIO) para persistência de blobs.

### 4.4 PID Provider

- Provê PIDs para arquivos XML enviados via API (`provide_pid_for_file`).
- Reconciliação de PIDs (`ClassicWebsiteArticlePidTracker`) com filtros
  ampliados em `update_pid_status` (ver commits `1d3f87b`, `7a2bee0`).
- Correção em massa de `pid_v2` (`task_fix_pid_v2`).
- Deduplicação automática de registros duplicados.

### 4.5 Publicação no site novo

- Clientes em `publication/api/`: `document.py`, `issue.py`, `journal.py`,
  `pressrelease.py`, com `publication.py` como base.
- `ArticleAvailability` registra a disponibilidade nos dois sites (novo e
  antigo) e a regra de publicação aplicada.
- Tarefa `publication.tasks.task_check_article_availability` valida URLs de
  artigos.

### 4.6 Observabilidade e auditoria

- `tracker.UnexpectedEvent.create(e, exc_traceback, detail=...)` é o padrão
  usado por todas as tarefas para registrar exceções com contexto
  estruturado.
- `CommonControlField` (em `core.models`) garante que todos os modelos
  principais carreguem `creator`, `updated_by`, `created` e `updated`.
- Snippets/ViewSets do Wagtail devem usar `core.views.CommonControlFieldViewSet`
  para preencher automaticamente `creator`/`updated_by` a partir de
  `request.user`.

### 4.7 API REST e autenticação

- DRF + `djangorestframework-simplejwt` para autenticação por JWT.
- Roteador em `config/api_router.py`; endpoints expostos pelo `pid_provider`
  e por `collection` (`WebSiteConfigurationEndpoint`).

### 4.8 Painel administrativo (Wagtail)

- Ordenação dos menus em `config/menu.py`
  (`WAGTAIL_MENU_APPS_ORDER` na 2.x começa em `"Tarefas"`).
- *Hooks* por app (`*/wagtail_hooks.py`) registram ViewSets/SnippetViewSets.

---

## 5. Estrutura de diretórios (alto nível)

```
scms-upload/  (branch main, v2.x)
├── article/             # Modelo Article + relacionados
├── bigbang/             # Bootstrap inicial do sistema
├── collection/          # Coleções SciELO e configuração de site
├── compose/             # Dockerfiles e scripts dev/prod
├── config/              # Settings Django, Celery, URLs, menu Wagtail
├── core/                # Tipos e utilitários comuns
├── core_settings/
├── django_celery_beat/
├── docs/                # Documentação Sphinx (este diretório)
│   ├── pid_provider/    # Guias EN/ES/PT do PID Provider
│   ├── processing/      # Guias de rastreamento de PIDs
│   └── v2.x/            # ← este documento
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
├── requirements/        # Pinned dependencies (base/local/production)
├── team/
├── tracker/             # Eventos, relatórios, status de progresso
├── upload/              # Código presente, mas DESABILITADO em INSTALLED_APPS
├── local.yml            # docker-compose desenvolvimento
├── production.yml       # docker-compose produção
├── manage.py
└── README.md
```

---

## 6. Como executar (desenvolvimento)

Resumo do `Makefile`:

```bash
make build compose=local.yml   # build da stack local
make up                        # subir containers
make django_migrate            # aplicar migrações
make django_createsuperuser    # criar usuário admin
make django_test               # rodar testes
make stop                      # parar containers
```

A documentação Sphinx pode ser servida com:

```bash
docker-compose -f local.yml up docs
```

---

## 7. Convenções importantes

- **`CommonControlField`**: todos os modelos relevantes herdam para auditoria
  automática (criado/atualizado por/em).
- **Sanitização de campos JSON (`detail`)**: tentar `json.dumps`; em falha,
  aplicar `core.utils.sanitize.sanitize_for_json` (que sanitiza apenas
  `str/dict/list/tuple` e devolve outros tipos inalterados).
- **`BaseProc.get_or_create`**: trata `MultipleObjectsReturned` removendo
  duplicatas e mantendo a mais recente, dado que não há *unique constraint*
  em `(collection, pid)`.
- **`proc/controller.py`** é apenas uma fachada de compatibilidade — a
  superfície pública é definida em `__all__`.
- **ViewSets Wagtail** devem estender `core.views.CommonControlFieldViewSet`
  para preencher `creator`/`updated_by` automaticamente.
- Mensagens de UI, *issues* e PRs no repositório seguem em **português**.

---

## 8. Documentos relacionados

- Guias do PID Provider: [`docs/pid_provider/`](../pid_provider/)
  (`guide_task_load_records_*.md` em EN/ES/PT-BR).
- Guias de rastreamento de PIDs do classic website:
  [`docs/processing/`](../processing/)
  (`guide_task_track_classic_website_article_pids_*.md`).
- Documentação Sphinx geral: [`docs/index.rst`](../index.rst).

---

## 9. Versão de referência

Este documento foi escrito a partir do estado do branch `main` em
`v2.12.0rc6`. Mudanças posteriores podem alterar nomes de tarefas,
status e campos; sempre confronte com o código atual.
