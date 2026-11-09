"""
Preenche network_classification das coleções que estão sem esse dado, a
partir do articlemeta, com a mesma função usada pela tarefa
collection.tasks.task_complete_network_classification
(collection.network_classification_completion.complete).

network_classification identifica a coleção principal no registro de
artigos publicados em mais de uma coleção (PidProviderXML.register).

Na falta do dado no articlemeta (indisponível ou sem a coleção), infere
pelo nome da coleção: SciELO Saúde Pública é scielonetwork e thematic;
SciELO com nome de país, scielonetwork; demais, thematic.

Nunca interrompe a migração: em caso de erro, o problema é informado e a
tarefa completa o restante (é idempotente: só altera coleções sem o dado).
"""

import logging

from django.db import migrations


def complete_network_classification(apps, schema_editor):
    from collection import network_classification_completion as completion

    try:
        result = completion.complete(apps)
    except Exception as e:
        logging.exception(e)
        print(
            f"\n  complete_network_classification: error ({type(e).__name__}: {e}). "
            "Run collection.tasks.task_complete_network_classification"
        )
        return

    if not (result["updated"] or result["not_found"]):
        return
    print(f"\n  complete_network_classification: {result}")
    if result["inferred"]:
        print(
            "  complete_network_classification: inferred from the collection "
            f"name: {result['inferred']}. Check network_classification in the admin"
        )
    if result["not_found"]:
        print(
            "  complete_network_classification: unable to complete (no data in "
            f"articlemeta and no name): {result['not_found']}. Fill in "
            "network_classification in the admin"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("collection", "0006_collection_platform_status_network_classification"),
    ]

    operations = [
        migrations.RunPython(
            complete_network_classification,
            migrations.RunPython.noop,
            elidable=True,
        ),
    ]
