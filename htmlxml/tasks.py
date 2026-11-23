from django.contrib.auth import get_user_model

from config import celery_app


@celery_app.task(bind=True)
def task_review_html2xml(
    self,
    user_id=None,
    username=None,
    collection_acron_list=None,
    journal_acron_list=None,
    updated_from=None,
    updated_to=None,
    only_not_reviewed=False,
    limit=None,
):
    """
    Revisa conversões HTML -> XML já feitas, sem reconverter (ver
    ``htmlxml.review``): grava as categorias de problema de cada conversão,
    para a revisão em Processing > HTML to XML review. Pode ser agendada no
    admin do celery beat (ex.: uma vez, após o deploy, para as conversões
    existentes).
    """
    from htmlxml.review import queryset_to_review, review_many

    User = get_user_model()
    user = None
    if user_id:
        user = User.objects.filter(pk=user_id).first()
    elif username:
        user = User.objects.filter(username=username).first()
    qs = queryset_to_review(
        collection_acron_list=collection_acron_list,
        journal_acron_list=journal_acron_list,
        updated_from=updated_from,
        updated_to=updated_to,
        only_not_reviewed=only_not_reviewed,
    )
    return review_many(qs, user=user, limit=limit)
