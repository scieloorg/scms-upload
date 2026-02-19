# Tabela de Permissões por Grupo de Usuário - Referência Rápida

## Legenda
- ✅ = Acesso Completo (Criar, Ler, Atualizar, Deletar)
- 👁️ = Somente Leitura
- ❌ = Sem Acesso

## Matriz de Permissões

| Módulo | Super-admin | Admin Coleção | Analista | Produtor XML | Gestor Periódico | Gestor Empresa | Revisor |
|--------|------------|---------------|----------|--------------|------------------|----------------|---------|
| **Upload** (Gestão de pacotes XML) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Article** (Artigos) | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | 👁️ |
| **Journal** (Periódicos) | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Issue** (Fascículos) | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| **Collection** (Coleções) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Team** (Equipes) | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ |
| **Institution** (Instituições) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Location** (Localizações) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Migration** (Migrações) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **DOI** (Gestão DOI) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **PID Provider** (Gestão PID) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Publication** (Publicações) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Package** (Rastreamento) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Proc** (Processos) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Tracker** (Rastreador) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Files Storage** (Armazenamento) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **HTML/XML** (Gestão HTML/XML) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Researcher** (Pesquisadores) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Core Settings** (Configurações) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Celery Beat** (Tarefas) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

## Descrição dos Grupos

### 🔴 Superadmin
**Acesso**: TOTAL  
**Quem**: Administradores do sistema  
**Pode**:
- Acessar todos os módulos
- Gerenciar configurações do sistema
- Gerenciar todos os usuários e grupos
- Acesso irrestrito a todas as funcionalidades

---

### 🟠 Admin Coleção
**Acesso**: AMPLO  
**Quem**: Administradores de coleções SciELO  
**Pode**:
- Gerenciar coleções, periódicos e artigos
- Configurar integrações e armazenamento
- Supervisionar uploads e processos
- Gerenciar equipes e instituições

**Não Pode**:
- Usar funções de produtor XML (upload direto)

---

### 🟡 Analista
**Acesso**: REVISÃO E VALIDAÇÃO  
**Quem**: Analistas de qualidade  
**Pode**:
- Revisar e validar pacotes XML
- Analisar artigos e fascículos
- Acompanhar processos e rastreamento
- Gerenciar DOIs e instituições

**Não Pode**:
- Criar uploads (apenas revisar)
- Gerenciar coleções ou periódicos
- Configurar sistema

---

### 🟢 Produtor XML
**Acesso**: UPLOAD LIMITADO  
**Quem**: Produtores de conteúdo XML  
**Pode**:
- Fazer upload de pacotes XML
- Ver e gerenciar seus próprios pacotes
- Acompanhar status dos uploads

**Não Pode**:
- Ver pacotes de outros produtores
- Aprovar ou rejeitar pacotes
- Acessar configurações administrativas

**Nota**: Acesso mais restrito, focado apenas em suas próprias submissões

---

### 🔵 Gestor de Periódico
**Acesso**: GESTÃO DE PERIÓDICO  
**Quem**: Editores e gestores de periódicos específicos  
**Pode**:
- Gerenciar artigos e fascículos do seu periódico
- Gerenciar equipe do periódico
- Ver informações do periódico

**Não Pode**:
- Fazer upload de pacotes XML
- Gerenciar outros periódicos
- Acessar módulos administrativos do sistema

---

### 🟣 Gestor de Empresa
**Acesso**: GESTÃO DE EMPRESA  
**Quem**: Gestores de empresas produtoras de XML  
**Pode**:
- Gerenciar equipe da empresa
- Ver e gerenciar contratos

**Não Pode**:
- Fazer upload direto
- Acessar conteúdo de periódicos
- Configurações administrativas

---

### ⚪ Revisor
**Acesso**: SOMENTE LEITURA  
**Quem**: Revisores de conteúdo  
**Pode**:
- Ver artigos
- Solicitar alterações em artigos (se configurado)

**Não Pode**:
- Editar ou criar qualquer conteúdo
- Acessar outros módulos

---

## Casos de Uso Comuns

### Caso 1: Novo Produtor XML
**Grupo**: Produtor XML  
**Acesso**: Upload module + Package tracking  
**Workflow**:
1. Faz login no sistema
2. Vê apenas menu "Upload" e "Package"
3. Cria novo upload de pacote XML
4. Acompanha status do seu pacote
5. Não vê pacotes de outros produtores

### Caso 2: Analista de Qualidade
**Grupo**: Analista  
**Acesso**: Upload (revisão) + Article + Issue + etc.  
**Workflow**:
1. Faz login no sistema
2. Vê menu completo de revisão
3. Acessa Upload → vê TODOS os pacotes
4. Analisa qualidade dos XMLs
5. Aprova ou rejeita pacotes
6. Gerencia DOIs e metadados

### Caso 3: Editor de Periódico
**Grupo**: Gestor de Periódico  
**Acesso**: Journal + Article + Issue + Team  
**Workflow**:
1. Faz login no sistema
2. Vê menu focado em gestão editorial
3. Gerencia artigos do seu periódico
4. Gerencia fascículos
5. Adiciona/remove membros da equipe editorial

### Caso 4: Administrador da Coleção
**Grupo**: Admin Coleção  
**Acesso**: Quase tudo, exceto upload direto  
**Workflow**:
1. Faz login no sistema
2. Vê menu completo administrativo
3. Configura coleções e periódicos
4. Supervisiona todo o processo
5. Gerencia equipes e configurações

## Perguntas Frequentes

### P: Um usuário pode ter múltiplos grupos?
**R**: Sim! Um usuário pode pertencer a múltiplos grupos e terá acesso combinado de todos eles.

**Exemplo**: Usuário nos grupos "Analista" + "Gestor de Periódico" terá acesso a:
- Todos os módulos do Analista
- Todos os módulos do Gestor de Periódico
- União dos dois (sem duplicação)

### P: Como dar acesso total a alguém?
**R**: Existem duas opções:
1. Marcar `is_superuser=True` no cadastro do usuário (Django Admin)
2. Adicionar ao grupo "Superadmin" + dar permissões específicas necessárias

**Recomendação**: Use `is_superuser` apenas para admins técnicos. Para admins de negócio, use grupo "Admin Coleção".

### P: Produtor XML não vê seus pacotes, o que fazer?
**R**: Verificar:
1. Usuário está no grupo "Produtor XML"? (Django Admin → Usuários)
2. Usuário está associado a uma Collection permitida? (CollectionTeamMember)
3. Grupos foram criados? (Execute `python manage.py create_user_groups`)

### P: Como adicionar um novo módulo ao sistema?
**R**: 
1. Adicionar à matriz em `core/users/user_groups.py`
2. Criar `permission_helper.py` para o novo app
3. Atualizar `wagtail_hooks.py` do app
4. Adicionar ao mapeamento de menu em `core/wagtail_hooks.py`

Ver `docs/PERMISSIONS_MATRIX.md` seção "Extensão do Sistema"

### P: Revisor pode editar artigos?
**R**: Por padrão, NÃO. Revisor tem acesso somente leitura. Se precisar de acesso de edição, considere:
- Adicionar ao grupo "Analista" (se for fazer revisões técnicas)
- Ou criar novo grupo "Editor" com permissões específicas

## Comandos Úteis

```bash
# Criar os grupos inicialmente
python manage.py migrate  # Automático via migration
# OU
python manage.py create_user_groups  # Manual

# Adicionar usuário a grupo (shell)
python manage.py shell
>>> from django.contrib.auth import get_user_model
>>> from django.contrib.auth.models import Group
>>> User = get_user_model()
>>> user = User.objects.get(username='maria')
>>> group = Group.objects.get(name='Analista')
>>> user.groups.add(group)

# Ver grupos de um usuário
>>> user.groups.all()

# Ver todos os usuários de um grupo
>>> Group.objects.get(name='Analista').user_set.all()
```

## Troubleshooting

| Problema | Solução |
|----------|---------|
| Menu items não aparecem | 1. Verificar se usuário está no grupo correto<br>2. Limpar cache do navegador<br>3. Fazer logout/login |
| Erro "Permission denied" | 1. Verificar grupos do usuário<br>2. Verificar se app está na matriz de permissões<br>3. Verificar CollectionTeamMember (para Upload) |
| Grupos não existem | Executar `python manage.py create_user_groups` |
| Produtor vê pacotes de outros | Verificar implementação de `get_queryset()` no ModelAdmin |

---

**Última atualização**: 2026-02-19  
**Versão do documento**: 1.0
