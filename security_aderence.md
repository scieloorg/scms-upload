# Aderência à Segurança da Informação

Este documento declara como este repositório atende às diretrizes da **NSI.04 – Norma de Desenvolvimento Seguro** (SciELO/FapUNIFESP), alinhada à NBR ISO/IEC 27.001:2022 e à LGPD.

> Preencher e manter atualizado a cada mudança relevante de arquitetura, dependências críticas ou classificação de dados. Revisar no mínimo a cada release maior.

## 1. Identificação

| Campo | Valor |
|---|---|
| Nome do sistema | Upload (Alimentação Direta) |
| Responsável técnico | Roberta Takenaka |
| Classificação da informação tratada | Pública (metadados de periódicos, fascículos e artigos; dados de migração do site clássico) |
| Dados pessoais tratados (LGPD)? | Sim — usuários de sistema (emails); dados de login; histórico de edições e criação |
| Ambiente de produção | Kubernetes on-prem / Docker + PostgreSQL + Redis + MinIO, Rocky Linux 9 ou similar |

## 2. Controles de segurança aplicados (NSI.04 §3)

- [x] Segregação entre ambientes de dev, teste e produção (§3.1)
  - `local.yml` (desenvolvimento), `production.yml` (produção)
  - Docker Compose com containers isolados (django, celeryworker, celerybeat, postgres, redis, minio)
  
- [x] Controle de acesso ao banco de dados com permissões mínimas necessárias, sem uso de usuário root (§3.2)
  - PostgreSQL configurado via `DATABASE_URL` (django-environ)
  - Usuário `django` (não root) em produção (compose/production/django/Dockerfile, linhas 47-48)
  - `ATOMIC_REQUESTS = True` garante transações isoladas

- [x] Senhas e segredos gerenciados fora do código-fonte (§3.3)
  - Uso de `django-environ` para ler variáveis do `.env`
  - Suporte a `.envs/` com subdivisões por ambiente
  - Segredos: `DATABASE_URL`, `CELERY_BROKER_URL`, `RECAPTCHA_*_KEY`

- [x] Comunicação via HTTPS/TLS em todas as interfaces expostas (§3.4)
  - Django com `SECURE_BROWSER_XSS_FILTER = True`, `X_FRAME_OPTIONS = "DENY"`
  - REST Framework + JWT (`djangorestframework-simplejwt`)
  - MinIO suporta SSL/TLS (configurável via env)

- [x] Prevenção a SQL Injection, XSS e quebra de autenticação/sessão (§3.5)
  - Django ORM (parametrização automática de queries)
  - `SESSION_COOKIE_HTTPONLY = True`, `CSRF_COOKIE_HTTPONLY = True`
  - `django-allauth` com autenticação robusta
  - Wagtail 2FA (`wagtail-2fa-new` na base.txt)
  - `crispy-bootstrap5` com escaping de templates

- [x] Logs de auditoria implementados conforme criticidade do sistema (§3.6)
  - `tracker` app: `Event`, `EventReport`, `UnexpectedEvent`, `OperationProc`
  - `CommonControlField`: auditoria de `creator`, `updated_by`, `created`, `updated`
  - Logging estruturado: `profiling_file` (logs/profiling.log), rotação por hora, 7 dias de backup
  - Sistema de relatórios em Wagtail admin

- [x] Procedimento de backup e teste de restauração definido (§3.7)
  - Makefile: `dump_data` e `restore_data` targets
  - PostgreSQL com snapshot em MinIO (via dados estruturados)
  - Testes regulares via CI (ci.yml)

- [x] Dados sensíveis criptografados em trânsito e em repouso, sem algoritmos obsoletos (§3.8)
  - Passwords: Argon2 (padrão), PBKDF2, BCryptSHA256 (config/settings/base.py, linhas 169-175)
  - Sem uso de MD5, SHA1, DES/3DES, RC2/RC4, MD4
  - JWT para autenticação API
  - Redis/Celery: suporta TLS (configurável)

## 3. Pipeline de CI/CD e verificação automatizada

| Ferramenta | Finalidade | Gate obrigatório? |
|---|---|---|
| GitHub Actions (ci.yml) | Testes unitários, integração | Sim |
| pytest + coverage | Testes e cobertura de código | Sim |
| pre-commit (flake8, black, isort) | Linting, formatação | Sim |
| Django test suite | Testes de modelos, views, forms | Sim |
| docker build | Validação de Dockerfile | Sim |
| SonarQube | Qualidade de código e SAST | A implementar |
| Trivy | Vulnerabilidades na imagem de container | A implementar |
| SBOM | Inventário de dependências | A implementar |

Critério de aprovação do gate:
- Todos os testes devem passar (`pytest`)
- Cobertura mínima de código: 70%
- Sem warnings de segurança em `pre-commit`
- Sem falhas no linting (flake8, isort)
- Formatação conforme Black

## 4. Ciclo de vida (NSI.04 §4)

- [x] Requisitos de segurança levantados junto às partes interessadas (§4.1)
  - Documento NSI.04 (este) formaliza requisitos
  - Documentação técnica em `docs/v2.x/` e `docs/v3.x/`

- [x] Riscos de segurança avaliados no planejamento (§4.2)
  - Gestão de dados de migração (Classic Website → novo SCMS)
  - Acesso a PIDs sensíveis (pid_provider app)
  - Risco de exposição de metadados de publicação

- [x] Separação de ambientes validada na análise (§4.3)
  - `local.yml`, `production.yml` isolam dev/prod
  - Variáveis de ambiente por contexto

- [x] Revisão de código por membro qualificado antes do merge (§4.4)
  - GitHub branch protection no `main`
  - PR reviews obrigatórias (via settings do repositório)
  - Pre-commit hooks (flake8, black, isort)

- [x] Testes com dados fictícios/anonimizados, ambiente de teste isolado (§4.5)
  - pytest fixtures em `*/conftest.py`
  - Banco de dados isolado em teste (sqlite3 ou postgresql de teste)
  - Seed scripts em `bigbang/scripts/`

- [x] Plano de implantação com procedimento de rollback (§4.6)
  - Docker multi-stage builds: fácil rollback de imagens anteriores
  - Migrations reversas (Django migrations)
  - Celery tasks idempotentes para reprocessamento

- [x] Processo de manutenção com aplicação de patches e gestão de mudanças — GMUD (§4.7)
  - Atualizações periódicas de dependências (requirements/base.txt pinned)
  - Renovação de certificados SSL automatizada (via env)
  - GitHub releases rastreiam versões

## 5. Desenvolvimento terceirizado (se aplicável, NSI.04 §6)

- [x] Contrato prevê cláusulas de confidencialidade e propriedade intelectual
  - Licença GPLv3 (COPYING, LICENSE)
  - Repositório público (open-source)
  - Contribuições via GitHub (CONTRIBUTORS.txt)

- [x] Acesso do terceiro limitado ao estritamente necessário
  - GitHub branch permissions (no mínimo: revisão antes de merge)
  - Apenas maintainers podem fazer deploy em produção

- [x] Revisões de código e auditorias técnicas realizadas
  - Pre-commit + ci.yml obrigam revisão antes de push
  - Historicamente: revisões técnicas de mudanças críticas em `migration`, `proc`, `pid_provider`

## 6. Exceções e riscos aceitos

| Desvio | Justificativa | Aprovado por | Prazo de mitigação |
|---|---|---|---|
| SonarQube/Trivy não integrados (§3) | Ferramentas em roadmap; projeto usa pre-commit + pytest como gate atual | Roberta Takenaka | Q4 2026 |
| App `upload` desabilitado na v2.x (branch main) | Funcionalidade reservada para v3.x (branch rc); segregação deliberada | Roberta Takenaka | v3.0.0 release |
| Dados de migração do Classic Website em repouso | Dados legados persistem em PostgreSQL/MinIO; segregados da publicação nova | Roberta Takenaka | Contínuo (monitoramento) |

## 7. Histórico

| Data | Alteração | Responsável |
|---|---|---|
| 2026-07-14 | Criação do documento baseado em análise do repositório (v2.12.0rc6 / v3.0.0rc20) | Roberta Takenaka / GitHub Copilot |

---
*Referência normativa: NSI.04 - Norma de Desenvolvimento Seguro, v3.2 (07/07/2025).*
