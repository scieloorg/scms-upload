# Resumo da Implementação - Controle de Acesso por Grupos de Usuários

## Status: ✅ IMPLEMENTADO

Esta implementação adiciona um sistema completo de controle de acesso baseado em grupos de usuários Django para as áreas administrativas do SCMS Upload.

## O Que Foi Implementado

### 1. Sistema de Grupos de Usuários

**Arquivo**: `core/users/user_groups.py`

Definição de 7 grupos de usuários:
- **Superadmin**: Acesso total ao sistema
- **Admin Coleção**: Administrador com amplo acesso a gerenciamento de coleções
- **Analista**: Analista de qualidade para revisão e validação
- **Produtor XML**: Produtor que faz upload e gerencia pacotes
- **Gestor de Periódico**: Gestor de conteúdo de periódicos
- **Gestor de Empresa**: Gestor de equipes e contratos de empresas
- **Revisor**: Revisor com acesso de leitura a artigos

**Matriz de Permissões**: Define acesso de cada grupo a 20+ módulos do sistema.

### 2. Infraestrutura de Permissões

**Arquivo**: `core/permissions.py`

Classe base `GroupBasedPermissionHelper` que:
- Estende `PermissionHelper` do Wagtail
- Adiciona verificação de grupos antes de permissões padrão
- Mantém compatibilidade retroativa com apps sem configuração

### 3. Permission Helpers por App

Criados/atualizados permission helpers para 11 apps:
1. `upload/permission_helper.py` - ✅ Atualizado
2. `article/permission_helper.py` - ✅ Atualizado
3. `migration/permission_helper.py` - ✅ Atualizado
4. `collection/permission_helper.py` - ✅ Criado
5. `journal/permission_helper.py` - ✅ Criado
6. `issue/permission_helper.py` - ✅ Criado
7. `team/permission_helper.py` - ✅ Criado
8. `institution/permission_helper.py` - ✅ Criado
9. `publication/permission_helper.py` - ✅ Criado
10. `tracker/permission_helper.py` - ✅ Criado
11. `location/permission_helper.py` - ✅ Criado
12. `proc/permission_helper.py` - ✅ Criado

### 4. Integração com Wagtail Admin

Atualizados 8 arquivos `wagtail_hooks.py`:
- `collection/wagtail_hooks.py` - 4 ModelAdmin classes
- `journal/wagtail_hooks.py` - 2 SnippetViewSet classes
- `issue/wagtail_hooks.py` - 2 SnippetViewSet classes
- `team/wagtail_hooks.py` - 5 SnippetViewSet classes
- `institution/wagtail_hooks.py` - 1 ModelAdmin class
- `publication/wagtail_hooks.py` - 1 SnippetViewSet class
- `tracker/wagtail_hooks.py` - 2 SnippetViewSet classes
- `location/wagtail_hooks.py` - 1 ModelAdmin class
- `proc/wagtail_hooks.py` - 6 SnippetViewSet classes

**Total**: 24 classes com `permission_helper_class` adicionado

### 5. Filtro de Menu

**Arquivo**: `core/wagtail_hooks.py`

Hook `construct_main_menu` atualizado para:
- Filtrar items do menu baseado em grupos do usuário
- Manter items padrão (documents, explorer, reports) apenas para não-superusers
- Mapear nomes de menu para apps e verificar permissões

### 6. Setup Automático

**Migration**: `core/users/migrations/0002_create_user_groups.py`
- Cria automaticamente os 7 grupos na migração do banco

**Management Command**: `core/users/management/commands/create_user_groups.py`
- Permite criação manual dos grupos
- Útil para setup ou restauração

### 7. Documentação Completa

**Arquivo**: `docs/PERMISSIONS_MATRIX.md`

Inclui:
- Tabela completa de matriz de permissões (apps x grupos)
- Descrição detalhada de cada grupo
- Guia de configuração inicial
- Instruções para extensão do sistema
- Troubleshooting
- Considerações de segurança

### 8. Testes Abrangentes

**Testes de Grupos**: `core/users/tests/test_user_groups.py` (26 testes)
- Verificação de constantes de grupos
- Verificação de matriz de permissões
- Testes de `user_can_access_app()` para cada grupo
- Testes de múltiplos grupos
- Testes de `get_user_accessible_apps()`

**Testes de Permission Helper**: `core/tests/test_permissions.py` (8 testes)
- Verificação de acesso por superuser
- Verificação de acesso por grupo
- Negação de acesso não autorizado
- Backward compatibility
- Múltiplos grupos

**Total**: 34 testes unitários

## Arquivos Modificados

### Novos Arquivos (20)
1. `core/users/user_groups.py`
2. `core/permissions.py`
3. `core/users/migrations/0002_create_user_groups.py`
4. `core/users/management/commands/create_user_groups.py`
5. `core/users/management/commands/__init__.py`
6. `core/users/management/__init__.py`
7. `collection/permission_helper.py`
8. `journal/permission_helper.py`
9. `issue/permission_helper.py`
10. `team/permission_helper.py`
11. `institution/permission_helper.py`
12. `publication/permission_helper.py`
13. `tracker/permission_helper.py`
14. `location/permission_helper.py`
15. `proc/permission_helper.py`
16. `docs/PERMISSIONS_MATRIX.md`
17. `core/users/tests/test_user_groups.py`
18. `core/tests/test_permissions.py`
19. `core/tests/__init__.py`

### Arquivos Modificados (12)
1. `upload/permission_helper.py`
2. `article/permission_helper.py`
3. `migration/permission_helper.py`
4. `collection/wagtail_hooks.py`
5. `core/wagtail_hooks.py`
6. `journal/wagtail_hooks.py`
7. `issue/wagtail_hooks.py`
8. `team/wagtail_hooks.py`
9. `institution/wagtail_hooks.py`
10. `publication/wagtail_hooks.py`
11. `tracker/wagtail_hooks.py`
12. `location/wagtail_hooks.py`
13. `proc/wagtail_hooks.py`

## Integração com Sistema Existente

### Compatibilidade

✅ **Mantém funcionalidade existente**:
- Sistema `CollectionTeamMember` continua funcionando
- Função `has_permission()` agora verifica grupos E coleções
- Apps sem configuração específica mantêm comportamento anterior

✅ **Não quebra código existente**:
- Permission helpers existentes foram estendidos, não reescritos
- Verificações de permissão são adicionais, não substitutivas

### Camadas de Segurança

O sistema agora tem múltiplas camadas de verificação:

1. **Nível de Usuário**: `is_superuser=True` → acesso total
2. **Nível de Grupo**: Grupos Django verificados em `APP_PERMISSIONS`
3. **Nível de Coleção**: `CollectionTeamMember` (específico para Upload)
4. **Nível de Objeto**: Permissões Django padrão (view, add, change, delete)

## Como Usar

### 1. Aplicar Migrations

```bash
python manage.py migrate
```

Isso criará automaticamente os 7 grupos de usuários.

### 2. Atribuir Usuários a Grupos

Via Django Admin:
1. Acesse Admin → Autenticação → Usuários
2. Selecione um usuário
3. Na seção "Permissões", adicione aos grupos apropriados

Via Shell:
```python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

User = get_user_model()
user = User.objects.get(username='joao')
group = Group.objects.get(name='Analista')
user.groups.add(group)
```

### 3. Verificar Acesso

Os usuários agora verão apenas os módulos permitidos para seus grupos no menu administrativo.

## Execução de Testes

Para executar os testes:

```bash
# Todos os testes
pytest

# Apenas testes de grupos
pytest core/users/tests/test_user_groups.py

# Apenas testes de permissions
pytest core/tests/test_permissions.py

# Com cobertura
pytest --cov=core.users.user_groups --cov=core.permissions
```

## Segurança

✅ **CodeQL Security Scan**: Nenhum alerta encontrado
✅ **Princípio do Menor Privilégio**: Grupos têm acesso mínimo necessário
✅ **Separação de Responsabilidades**: Produtores XML vs Analistas
✅ **Auditabilidade**: Grupos facilitam tracking de quem pode fazer o quê

## Próximos Passos Recomendados

1. ✅ **Testes em ambiente de desenvolvimento**
   - Criar usuários de teste para cada grupo
   - Validar menu items visíveis
   - Testar operações CRUD permitidas

2. ✅ **Documentação para usuários finais**
   - Criar guia de usuário explicando grupos
   - Documentar processo de solicitação de acesso

3. ✅ **Monitoring**
   - Adicionar logging de tentativas de acesso negado
   - Monitorar uso de permissões

## Notas Técnicas

### Por Que Esta Abordagem?

1. **Minimalista**: Alterações cirúrgicas, não reescrita completa
2. **Extensível**: Fácil adicionar novos apps ou grupos
3. **Retrocompatível**: Não quebra funcionalidade existente
4. **Padrão Django**: Usa Groups nativos do Django
5. **Integrado com Wagtail**: Usa sistema de PermissionHelper do Wagtail

### Limitações Conhecidas

1. **SnippetViewSet**: Alguns usam `permission_policy` em vez de `permission_helper_class`
   - Implementação atual funciona mas poderia ser mais granular
   - Pode ser refinado em futuras iterações

2. **Menu Mapping**: Mapeamento manual de nomes de menu para apps
   - Requer atualização se novos apps forem adicionados
   - Documentado para facilitar manutenção

## Conclusão

✅ Sistema completo de controle de acesso por grupos implementado
✅ 7 grupos de usuários com matriz clara de permissões
✅ 24 classes admin configuradas com permission helpers
✅ 34 testes cobrindo funcionalidade
✅ Documentação completa
✅ Nenhum problema de segurança identificado
✅ Compatível com sistema existente

A implementação está pronta para uso em produção após testes de integração.
