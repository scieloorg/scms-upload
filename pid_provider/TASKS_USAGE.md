# PID Provider no Upload

O Upload recebe XML/ZIP para ingestão direta de conteúdo novo ou atualizado.
`PidRequester` solicita o PID ao Core e sincroniza o registro local. O Core
controla fontes por URL com `ArticleSource`; esse controle não pertence à
app compartilhada `pid_provider`.

## Métodos compartilhados

Todos os métodos de `BasePidProvider` continuam disponíveis, inclusive os
métodos de URI. Eles obtêm/processam o XML e retornam dados ou erros, sem
persistir um controle de fontes por URL. O PID esperado, quando informado,
é conferido antes do registro. A auditoria de registro permanece disponível.

## Tarefas do Upload

- `provide_pid_for_file`: recebe um XML/ZIP para o PID Provider local.
- `task_fix_pid_v2` e `subtask_fix_pid_v2`: corrigem os PIDs legados.

O fluxo de ingestão direta usa `PidRequester` para solicitar o PID ao Core.
Coleta e retry do OPAC e seus agendamentos foram retirados do Upload.

## Dados legados de XMLURL

O modelo e o painel XMLURL foram removidos. A migração aceita uma tabela já
removida pela v2 e remove tabelas vazias. Se houver registros, interrompe antes
de removê-los: o destino desses dados deve ser resolvido previamente, por
preservação/exportação ou decisão explícita de descarte. Arquivos antigos
não são apagados pela migração.
