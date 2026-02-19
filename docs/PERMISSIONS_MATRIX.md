# Matriz de Permissões por Grupo de Usuário

Este documento descreve a matriz de permissões implementada no sistema SCMS Upload, definindo quais grupos de usuários têm acesso a quais áreas administrativas.

## Grupos de Usuários

O sistema possui 7 grupos de usuários com diferentes níveis de acesso:

### 1. **Superadmin**
- **Descrição**: Acesso completo ao sistema com todas as permissões
- **Características**: 
  - Usuários com flag `is_superuser=True` têm acesso automático a tudo
  - Podem gerenciar todos os módulos e configurações do sistema

### 2. **Admin Coleção**
- **Descrição**: Administrador de coleção com amplo acesso para gerenciar coleções
- **Características**: 
  - Acesso a praticamente todos os módulos, exceto alguns específicos de produtores XML
  - Pode configurar e gerenciar coleções, periódicos e artigos

### 3. **Analista**
- **Descrição**: Analista de qualidade que revisa e valida pacotes
- **Características**: 
  - Acesso ao módulo de upload para análise de pacotes
  - Pode revisar artigos, questões e acompanhar processos
  - Não pode criar novos uploads, apenas analisar os existentes

### 4. **Produtor XML**
- **Descrição**: Produtor de XML que faz upload e gerencia pacotes
- **Características**: 
  - Acesso ao módulo de upload para criar e gerenciar seus próprios pacotes
  - Visualização restrita aos próprios pacotes criados
  - Não tem acesso a funções administrativas

### 5. **Gestor de Periódico**
- **Descrição**: Gestor de periódico que gerencia conteúdo de periódicos
- **Características**: 
  - Pode gerenciar artigos, questões e contratos do seu periódico
  - Acesso ao módulo de equipe para gerenciar membros do periódico

### 6. **Gestor de Empresa**
- **Descrição**: Gestor de empresa que gerencia equipe e contratos da empresa
- **Características**: 
  - Pode gerenciar membros da equipe da empresa
  - Visualiza e gerencia contratos com periódicos

### 7. **Revisor**
- **Descrição**: Revisor de conteúdo com acesso de leitura a artigos
- **Características**: 
  - Acesso somente leitura a artigos
  - Pode solicitar alterações em artigos

## Matriz de Permissões

A tabela abaixo mostra quais grupos têm acesso a cada módulo do sistema:

| Módulo / App | Superadmin | Admin Coleção | Analista | Produtor XML | Gestor Periódico | Gestor Empresa | Revisor |
|--------------|-----------|---------------|----------|--------------|------------------|----------------|---------|
| **upload** - Gestão de pacotes e upload de XML | ✓ | ✓ | ✓ | ✓ | | | |
| **article** - Gestão de artigos | ✓ | ✓ | ✓ | | ✓ | | ✓ |
| **journal** - Gestão de periódicos | ✓ | ✓ | | | ✓ | | |
| **issue** - Gestão de fascículos | ✓ | ✓ | ✓ | | ✓ | | |
| **collection** - Gestão de coleções | ✓ | ✓ | | | | | |
| **team** - Gestão de equipes | ✓ | ✓ | | | ✓ | ✓ | |
| **institution** - Gestão de instituições | ✓ | ✓ | ✓ | | | | |
| **location** - Gestão de localizações | ✓ | ✓ | | | | | |
| **migration** - Gestão de migrações | ✓ | ✓ | | | | | |
| **doi** - Gestão de DOI | ✓ | ✓ | ✓ | | | | |
| **pid_provider** - Gestão de PID | ✓ | ✓ | | | | | |
| **publication** - Gestão de publicações | ✓ | ✓ | ✓ | | | | |
| **package** - Rastreamento de pacotes | ✓ | ✓ | ✓ | ✓ | | | |
| **proc** - Gestão de processos | ✓ | ✓ | ✓ | | | | |
| **tracker** - Sistema de rastreamento | ✓ | ✓ | ✓ | | | | |
| **files_storage** - Armazenamento de arquivos | ✓ | ✓ | | | | | |
| **htmlxml** - Gestão HTML/XML | ✓ | ✓ | ✓ | | | | |
| **researcher** - Gestão de pesquisadores | ✓ | ✓ | ✓ | | | | |
| **core_settings** - Configurações do sistema | ✓ | ✓ | | | | | |
| **django_celery_beat** - Agendamento de tarefas | ✓ | ✓ | | | | | |

## Como Funciona

### Verificação de Permissões

O sistema verifica permissões em múltiplos níveis:

1. **Nível de Usuário**: 
   - Superusers (`is_superuser=True`) têm acesso automático a tudo

2. **Nível de Grupo**: 
   - Função `user_can_access_app(user, app_name)` verifica se o usuário pertence a algum grupo permitido

3. **Nível de Coleção** (para módulo Upload):
   - Verificação adicional através de `CollectionTeamMember` para controle baseado em coleção

### Implementação Técnica

- **Arquivo de configuração**: `core/users/user_groups.py`
  - Define constantes de grupos via classe `UserGroups`
  - Define matriz `APP_PERMISSIONS` mapeando apps para grupos
  - Fornece funções auxiliares para verificação de acesso

- **Permission Helper Base**: `core/permissions.py`
  - Classe `GroupBasedPermissionHelper` estende `PermissionHelper` do Wagtail
  - Adiciona verificações de grupo antes das verificações padrão de permissão

- **Permission Helpers por App**: 
  - Cada app tem seu próprio `permission_helper.py`
  - Herda de `GroupBasedPermissionHelper` e define `app_name`

- **Menu Filtering**: `core/wagtail_hooks.py`
  - Hook `construct_main_menu` filtra items do menu baseado em grupos do usuário
  - Remove items de menu para apps que o usuário não pode acessar

## Configuração Inicial

### Criação de Grupos

Execute um dos seguintes comandos para criar os grupos:

```bash
# Via migration (automático ao rodar migrate)
python manage.py migrate

# Via management command (manual)
python manage.py create_user_groups
```

### Atribuição de Usuários a Grupos

Use o Django Admin ou shell para adicionar usuários a grupos:

```python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

User = get_user_model()
user = User.objects.get(username='joao')
group = Group.objects.get(name='Analista')
user.groups.add(group)
```

## Extensão do Sistema

Para adicionar um novo app ao sistema de permissões:

1. **Adicione o app à matriz** em `core/users/user_groups.py`:
   ```python
   APP_PERMISSIONS = {
       # ... existing apps ...
       "novo_app": [
           UserGroups.SUPERADMIN,
           UserGroups.ADMIN_COLLECTION,
       ],
   }
   ```

2. **Crie um permission helper** para o app:
   ```python
   # novo_app/permission_helper.py
   from core.permissions import GroupBasedPermissionHelper
   
   class NovoAppPermissionHelper(GroupBasedPermissionHelper):
       app_name = "novo_app"
   ```

3. **Use o helper no wagtail_hooks**:
   ```python
   # novo_app/wagtail_hooks.py
   from novo_app.permission_helper import NovoAppPermissionHelper
   
   class NovoAppModelAdmin(ModelAdmin):
       permission_helper_class = NovoAppPermissionHelper
       # ... rest of config ...
   ```

4. **Adicione ao mapeamento de menu** em `core/wagtail_hooks.py`:
   ```python
   menu_to_app_mapping = {
       # ... existing mappings ...
       'novo-app': 'novo_app',
   }
   ```

## Troubleshooting

### Usuário não vê módulo esperado

1. Verifique se o usuário pertence ao grupo correto
2. Verifique se o app está na matriz `APP_PERMISSIONS`
3. Verifique se o permission helper está configurado no wagtail_hooks
4. Para módulo Upload, verifique também `CollectionTeamMember`

### Grupo não existe

Execute o comando para criar grupos:
```bash
python manage.py create_user_groups
```

### Permissões não estão funcionando

1. Verifique se a migration `0002_create_user_groups` foi aplicada
2. Limpe o cache do navegador
3. Faça logout e login novamente
4. Verifique logs do Django para erros

## Considerações de Segurança

- **Superusers**: Sempre têm acesso total, use com cuidado
- **Grupos vs Permissões**: Este sistema usa grupos para controle de acesso no nível de app. Permissões específicas (create, edit, delete) ainda são controladas pelo sistema padrão do Django/Wagtail
- **CollectionTeamMember**: O módulo Upload tem camada adicional de segurança baseada em coleções
- **Backward Compatibility**: Apps sem configuração específica mantêm comportamento anterior
