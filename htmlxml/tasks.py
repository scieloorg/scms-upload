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


@celery_app.task(bind=True)
def task_reprocess_html2xml(self, user_id=None, ticket_id=None, problem_id=None, collection_ids=None):
    """
    Marca para reprocessamento os artigos afetados por um registro tipo
    issue (``ticket_id``) ou por um problema de coleção (``problem_id``),
    ver ``htmlxml.tickets``. Não converte: o fluxo regular da migração
    converte de novo os artigos marcados.
    """
    from htmlxml import tickets
    from htmlxml.models import Html2xmlProblem, Html2xmlTicket

    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    result = {}
    if ticket_id:
        ticket = Html2xmlTicket.objects.get(pk=ticket_id)
        result["ticket"] = tickets.reprocess_ticket(ticket, user=user, collection_ids=collection_ids)
    if problem_id:
        problem = Html2xmlProblem.objects.get(pk=problem_id)
        result["problem"] = tickets.reprocess_problem(problem, user=user)
    return result
