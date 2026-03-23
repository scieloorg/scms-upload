# Guia: task_track_classic_website_article_pids

## Propósito

A tarefa `proc.tasks.task_track_classic_website_article_pids` compara os PIDs de
artigos registrados no site clássico do SciELO (lidos a partir de um arquivo de
texto indicado em `ClassicWebsiteConfiguration.pid_list_path`) com os registros
`ArticleProc` já armazenados no sistema. Em seguida, atualiza o campo
`pid_status` de cada registro:

| Status | Significado |
|---|---|
| **matched** | O PID existe tanto no site clássico quanto em `ArticleProc` com `migrated_data` vinculado. |
| **missing** | O PID existe em `ArticleProc`, mas não possui `migrated_data` vinculado. |
| **exceeding** | O PID está presente em `ArticleProc`, mas não foi encontrado na lista de PIDs do site clássico. |

PIDs novos encontrados no arquivo do site clássico que ainda não possuem um
registro `ArticleProc` correspondente são criados automaticamente com status
**missing**.

### Pré-requisitos

| Requisito | Detalhes |
|---|---|
| **Configuração do site clássico** | Deve existir um registro `ClassicWebsiteConfiguration` para a coleção de destino, com um `pid_list_path` válido apontando para um arquivo de texto contendo um PID por linha. |
| **Coleção** | Deve existir pelo menos um registro `Collection`. |
| **Usuário** | Um usuário Django válido (por `username` ou `user_id`). |

---

## Como criar a tarefa periódica (django_celery_beat)

### Passo 1 – Acessar o painel de administração

1. Faça login no painel de administração do Wagtail (por exemplo, `https://<seu-dominio>/admin/`).
2. No menu lateral esquerdo, acesse **Settings > Periodic tasks**.

> Se você não visualizar este item de menu, verifique se o aplicativo
> `django_celery_beat` está instalado e se o seu usuário possui as
> permissões apropriadas.

### Passo 2 – Criar uma nova tarefa periódica

1. Clique em **Add periodic task**.
2. Preencha os campos obrigatórios:

| Campo | Valor |
|---|---|
| **Name** | Um nome descritivo, por exemplo `Track Classic Website PIDs (scl)` |
| **Task (registered)** | Selecione `proc.tasks.task_track_classic_website_article_pids` |
| **Enabled** | ✅ Marcado |

3. Escolha uma programação. Por exemplo, para executar uma vez ao dia, crie ou
   selecione um **Interval Schedule** de `1 day` ou um **Crontab Schedule**
   como `0 3 * * *` (todos os dias às 03:00).

### Passo 3 – Configurar os argumentos por palavra-chave (kwargs)

No campo **Keyword arguments (JSON)**, insira um objeto JSON com os
parâmetros que a tarefa aceita:

```json
{
  "username": "admin",
  "collection_acron": "scl"
}
```

#### Parâmetros disponíveis

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `username` | string | **sim** | Nome de usuário do usuário Django que será registrado como criador de quaisquer novos registros `ArticleProc`. |
| `user_id` | integer | não | Alternativa ao `username`. Se ambos forem fornecidos, `user_id` tem prioridade. |
| `collection_acron` | string | não | Acrônimo da coleção a ser processada (por exemplo, `"scl"` para Brasil). Se omitido, **todas** as coleções serão processadas. |

> **⚠️ Crítico:** O `username` ou `user_id` deve corresponder a um usuário
> existente. Se o usuário não for encontrado, a tarefa registrará um erro
> e pulará o processamento.

> **⚠️ Crítico:** Deve existir um registro `ClassicWebsiteConfiguration` com um
> `pid_list_path` válido para a coleção de destino. Se a configuração não
> existir ou o arquivo não puder ser lido, a tarefa falhará para essa
> coleção.

### Passo 4 – Salvar

Clique em **Save**. A tarefa será capturada pelo agendador Celery Beat de
acordo com a programação que você configurou.

---

## Verificação do resultado

### 1. Task Tracker (painel de administração do Wagtail)

Na barra lateral do painel de administração do Wagtail, acesse
**Task Tracker** (na seção Tracker). Procure entradas com o nome
`proc.tasks.task_track_classic_website_article_pids`. Cada entrada exibe:

- **Item** – O acrônimo da coleção processada (ou `all`).
- **Status** – `started`, `completed` ou `failed`.
- **Detail** – Um objeto JSON contendo:
  - `params`: os kwargs utilizados.
  - `events`: uma lista com as contagens de status de PID por coleção (por
    exemplo, `{"collection": "scl", "matched": 1200, "missing": 50,
    "exceeding": 3}`).
  - `exceptions`: quaisquer erros que tenham ocorrido.

### 2. Registros ArticleProc (painel de administração do Wagtail)

Navegue até a listagem de **ArticleProc** no painel de administração e filtre
por `pid_status` para verificar a distribuição:

- **matched** – artigos vinculados com sucesso.
- **missing** – artigos que precisam de atenção (sem `migrated_data`).
- **exceeding** – artigos no sistema, mas não na lista de PIDs do site clássico.

### 3. Django shell / verificação programática

```python
from proc.models import ArticleProc
from django.db.models import Count

# Resumo de pid_status para uma coleção
ArticleProc.objects.filter(
    collection__acron="scl"
).values("pid_status").annotate(total=Count("pid")).order_by("pid_status")
```

### 4. Logs do worker do Celery

Verifique a saída do worker do Celery para mensagens INFO e ERROR relacionadas
a `task_track_classic_website_article_pids`. Os erros também são registrados no
modelo `UnexpectedEvent`, acessível a partir do painel de administração do
Wagtail.
