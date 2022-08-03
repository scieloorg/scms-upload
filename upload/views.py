from django.shortcuts import redirect
from django.utils.translation import gettext as _


def finish_deposit(request):
    """
    This view function abilitates the user to finish deposit of a package through the graphic-interface.

    TODO: 
    """
    return redirect(request.META.get('HTTP_REFERER'))
