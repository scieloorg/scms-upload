from django.shortcuts import render, get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from core.controller import get_users

from .models import Article


def request_change(request):
    """
    This view function enables the user to request change.
    """
    if request.method == 'POST':
        return redirect(request.META.get('HTTP_REFERER'))

    else:
        pid_v2 = request.GET.get('pid_v2')

        if pid_v2:
            article = get_object_or_404(Article, pk=pid_v2)
            available_users = get_users()

            return render(
                request=request,
                template_name='modeladmin/article/request_change.html',
                context={
                    'article_index_url': 'article_article_modeladmin_index',
                    'article': article,
                    'available_users': available_users,
                    'report_title': _('Request Change'),
                    'report_subtitle': pid_v2,
                    }
            )

        return redirect(request.META.get('HTTP_REFERER'))
