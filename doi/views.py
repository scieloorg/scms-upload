"""
Views for Crossref DOI deposit operations.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from article.models import Article
from doi.tasks import task_deposit_doi_to_crossref

logger = logging.getLogger(__name__)


@login_required
def deposit_article_doi(request):
    """
    View para disparar o depósito do DOI de um artigo no Crossref.
    Acessível via botão no painel de administração do artigo ou pacote.
    """
    article_id = request.GET.get("article_id")
    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "/"

    if not article_id:
        messages.error(request, _("Article ID is required."))
        return HttpResponseRedirect(next_url)

    article = get_object_or_404(Article, pk=article_id)

    task_deposit_doi_to_crossref.apply_async(
        kwargs=dict(
            user_id=request.user.id,
            username=request.user.username,
            article_id=article.id,
            force=request.GET.get("force", "false").lower() == "true",
        )
    )

    messages.success(
        request,
        _(
            "DOI deposit for article '%(article)s' has been queued. "
            "Check the deposit status in the Crossref Deposits section."
        )
        % {"article": str(article)},
    )

    return HttpResponseRedirect(next_url)
