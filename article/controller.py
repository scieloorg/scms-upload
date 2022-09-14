from django.utils.translation import gettext_lazy as _

from article.models import Article

from . import exceptions



def get_or_create_official_article(official_issue, **kwargs):
    try:
        official_article, status = Article.objects.get_or_create(**kwargs)
    except Exception as e:
        raise exceptions.GetOrCreateDocumentError(
            _('Unable to get or create official article {} {} {}').format(
                str(kwargs), type(e), e
            )
        )
    return official_article
