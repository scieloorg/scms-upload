"""
Vincula ao documento na coleção (collection_pid_v2) os SPSPkg e Article
anteriores à separação por coleção, com a mesma função usada pela tarefa
article.tasks.task_complete_collection_pid_v2
(package.collection_pid_v2_completion.complete).

Para não prolongar o deploy, processa por no máximo
COLLECTION_PID_V2_MIGRATION_MAX_SECONDS segundos (variável de ambiente,
padrão 600; vazio ou "none": sem limite; 0: não processa). O que ficar
pendente é processado pela tarefa, a partir de model_name e last_id
informados na saída da migração (ou desde o início: é idempotente).

Nunca interrompe a migração por erro no vínculo: o erro é informado e a
tarefa completa o restante.

Sem transação única (atomic = False): cada vínculo é gravado em sua própria
transação, para que o progresso seja mantido e não haja bloqueio
prolongado das tabelas.
"""

import logging
import os

from django.db import migrations

DEFAULT_MAX_SECONDS = 600


def get_max_seconds():
    value = os.environ.get("COLLECTION_PID_V2_MIGRATION_MAX_SECONDS")
    if value is None:
        return DEFAULT_MAX_SECONDS
    if value.strip().lower() in ("", "none"):
        return None
    return int(value)


def complete_collection_pid_v2(apps, schema_editor):
    from package import collection_pid_v2_completion as completion

    try:
        unlinked = completion.count_unlinked(apps)
        if not any(unlinked.values()):
            return
        max_seconds = get_max_seconds()
        if max_seconds == 0:
            result = {"model_name": completion.MODEL_NAMES[0], "last_id": 0, "done": False}
        else:
            result = completion.complete(apps, batch_size=500, max_seconds=max_seconds)
        unlinked = completion.count_unlinked(apps)
    except Exception as e:
        logging.exception(e)
        print(
            f"\n  complete_collection_pid_v2: error ({type(e).__name__}: {e}). "
            "Run article.tasks.task_complete_collection_pid_v2"
        )
        return

    print(f"\n  complete_collection_pid_v2: {result.get('stats')}; unlinked: {unlinked}")
    if not result["done"]:
        print(
            "  complete_collection_pid_v2: pending. Run "
            "article.tasks.task_complete_collection_pid_v2 with "
            f"model_name={result['model_name']!r}, last_id={result['last_id']}"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("article", "0013_article_collection_pid_v2_keep_fields"),
        ("package", "0010_spspkg_collection_pid_v2_keep_fields"),
        ("pid_provider", "0019_collectionpidv2_sps_pkg_name"),
        ("proc", "0015_alter_articleproc_migration_status_and_more"),
    ]

    operations = [
        migrations.RunPython(
            complete_collection_pid_v2, migrations.RunPython.noop, elidable=True
        ),
    ]
