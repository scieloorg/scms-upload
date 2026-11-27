from datetime import date

from django.db.models import Count, F, Max, Min
from django.db.models.functions import ExtractYear
from django.utils.translation import gettext_lazy as _

from article import choices
from article.models import Article
from journal.models import Journal

GROUP_BY_ISSUE_YEAR = "issue_year"
GROUP_BY_PUB_YEAR = "pub_year"

GROUP_BY_OPTIONS = (
    (GROUP_BY_ISSUE_YEAR, _("Issue year (bibliographic strip)")),
    (GROUP_BY_PUB_YEAR, _("Online publication year")),
)

NOT_PROCESSED = "not-processed"


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def get_status_columns():
    columns = list(choices.DATA_AVAILABILITY_STATUS)
    columns.append((NOT_PROCESSED, _("Not processed")))
    return columns


def filter_articles(
    collection_acron=None, journal_id=None, pub_date_from=None, pub_date_to=None
):
    qs = Article.objects.all()
    if collection_acron:
        # subquery evita contagem duplicada pelo join com article_collections
        qs = qs.filter(
            pk__in=Article.objects.filter(
                article_collections__collection__acron=collection_acron
            ).values("pk")
        )
    if journal_id:
        qs = qs.filter(journal_id=journal_id)
    if pub_date_from:
        qs = qs.filter(first_publication_date__gte=pub_date_from)
    if pub_date_to:
        qs = qs.filter(first_publication_date__lte=pub_date_to)
    return qs


def get_journals(collection_acron=None):
    """Periódicos que têm artigos na coleção (todos, se não informada)."""
    journals = Journal.objects.all()
    if collection_acron:
        journals = journals.filter(
            pk__in=Article.objects.filter(
                article_collections__collection__acron=collection_acron
            ).values("journal_id")
        )
    return journals.order_by("title", "short_title")


def get_pub_date_range(collection_acron=None, journal_id=None):
    """Menor e maior data de publicação online dos artigos filtrados."""
    result = filter_articles(
        collection_acron=collection_acron, journal_id=journal_id
    ).aggregate(min=Min("first_publication_date"), max=Max("first_publication_date"))
    return result["min"], result["max"]


def get_filter_options(collection_acron=None, journal_id=None):
    """
    Opções dos filtros dependentes:
    coleção -> periódicos; coleção + periódico -> intervalo de datas.
    """
    pub_date_min, pub_date_max = get_pub_date_range(collection_acron, journal_id)
    return {
        "journals": [
            {"id": j.id, "label": str(j)} for j in get_journals(collection_acron)
        ],
        "pub_date_min": pub_date_min.isoformat() if pub_date_min else "",
        "pub_date_max": pub_date_max.isoformat() if pub_date_max else "",
    }


def percent(value, total):
    return round(value * 100 / total, 2) if total else 0


def build_data_availability_report(queryset, group_by=GROUP_BY_ISSUE_YEAR):
    """
    Contabiliza Article.data_availability_status por ano.

    Retorna dict com:
        columns: [(status, label), ...]
        rows: [{"year", "total", "cells": [{"status", "count", "percent"}]}]
        totals: {"total", "cells": [...]}
    """
    if group_by == GROUP_BY_PUB_YEAR:
        year_expr = ExtractYear("first_publication_date")
    else:
        year_expr = F("issue__publication_year")

    data = (
        queryset.order_by()
        .annotate(year=year_expr)
        .values("year", "data_availability_status")
        .annotate(n=Count("pk"))
    )

    columns = get_status_columns()
    by_year = {}
    for item in data:
        year = str(item["year"]) if item["year"] else None
        status = item["data_availability_status"] or NOT_PROCESSED
        counts = by_year.setdefault(year, {})
        counts[status] = counts.get(status, 0) + item["n"]

    def make_row(year, counts):
        total = sum(counts.values())
        return {
            "year": year,
            "total": total,
            "cells": [
                {
                    "status": status,
                    "count": counts.get(status, 0),
                    "percent": percent(counts.get(status, 0), total),
                }
                for status, _label in columns
            ],
        }

    # anos em ordem decrescente; sem ano por último
    years = sorted((y for y in by_year if y), reverse=True)
    if None in by_year:
        years.append(None)
    rows = [make_row(year, by_year[year]) for year in years]

    all_counts = {}
    for counts in by_year.values():
        for status, n in counts.items():
            all_counts[status] = all_counts.get(status, 0) + n
    totals = make_row(None, all_counts)

    return {"columns": columns, "rows": rows, "totals": totals}
