import logging

from django.utils.translation import gettext_lazy as _

from issue.models import Issue

from . import exceptions


def get_or_create(
        official_journal,
        year,
        volume,
        number,
        supplement,
        creator,
        initial_month_name=None,
        initial_month_number=None,
        final_month_name=None,
        ):
    return Issue.get_or_create(
        official_journal,
        year,
        volume,
        number,
        supplement,
        creator,
        initial_month_name=None,
        initial_month_number=None,
        final_month_name=None,
    )
