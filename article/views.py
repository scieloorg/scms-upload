# Create your views here.
import logging

from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from wagtail_modeladmin.views import CreateView, EditView, InspectView

from .models import Article, RelatedItem, RequestArticleChange, choices


class ArticleCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class RelatedItemCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class RequestArticleChangeCreateView(CreateView):
    def get_instance(self):
        change_request_obj = super().get_instance()

        article_id = self.request.GET.get("article_id")
        if article_id:
            change_request_obj.article = Article.objects.get(pk=article_id)
        return change_request_obj

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class ArticleAdminInspectView(InspectView):
    def get_context_data(self):
        # FIXME
        # Colocar packages como download para package
        data = {
            "status": self.instance.status,
            # "packages": self.instance.package_set.all(),
        }

        if self.instance.status in (
            choices.AS_REQUIRE_UPDATE,
            choices.AS_REQUIRE_ERRATUM,
        ):
            data["requested_changes"] = []
            for rac in self.instance.requestarticlechange_set.all():
                data["requested_changes"].append(rac)

        return super().get_context_data(**data)


def download_package(request):
    """
    This view function enables the user to download the package through admin
    """
    article_id = request.GET.get("article_id")

    if article_id:
        article = get_object_or_404(Article, pk=article_id)

    try:
        package = article.get_package()
        response = HttpResponse(package["content"], content_type="application/zip")
        response["Content-Disposition"] = "attachment; filename=" + package["filename"]
        return response
    except Exception as e:
        logging.exception(e)
        raise Http404


def _get_data_availability_filters(request):
    from article import reports

    journal_id = request.GET.get("journal") or None
    if journal_id and not journal_id.isdigit():
        journal_id = None
    group_by = request.GET.get("group_by")
    if group_by not in dict(reports.GROUP_BY_OPTIONS):
        group_by = reports.GROUP_BY_ISSUE_YEAR
    return {
        "collection_acron": request.GET.get("collection") or None,
        "journal_id": journal_id,
        "pub_date_from": reports.parse_date(request.GET.get("pub_date_from")),
        "pub_date_to": reports.parse_date(request.GET.get("pub_date_to")),
        "group_by": group_by,
    }


def data_availability_report(request):
    """
    Relatório público: Article.data_availability_status por ano,
    com total e porcentagem, filtrável por coleção, periódico e
    data de publicação online (first_publication_date).
    """
    from article import reports
    from collection.models import Collection

    filters = _get_data_availability_filters(request)
    qs = reports.filter_articles(
        collection_acron=filters["collection_acron"],
        journal_id=filters["journal_id"],
        pub_date_from=filters["pub_date_from"],
        pub_date_to=filters["pub_date_to"],
    )
    report = reports.build_data_availability_report(qs, group_by=filters["group_by"])

    if request.GET.get("format") == "csv":
        return _data_availability_report_csv(report)

    pub_date_min, pub_date_max = reports.get_pub_date_range(
        filters["collection_acron"], filters["journal_id"]
    )
    return render(
        request,
        "article/report/data_availability.html",
        {
            "report": report,
            "collections": Collection.objects.order_by("acron"),
            "journals": reports.get_journals(filters["collection_acron"]),
            "group_by_options": reports.GROUP_BY_OPTIONS,
            "pub_date_min": pub_date_min.isoformat() if pub_date_min else "",
            "pub_date_max": pub_date_max.isoformat() if pub_date_max else "",
            "filters": {
                "collection": filters["collection_acron"] or "",
                "journal": filters["journal_id"] or "",
                "pub_date_from": (
                    filters["pub_date_from"].isoformat()
                    if filters["pub_date_from"]
                    else ""
                ),
                "pub_date_to": (
                    filters["pub_date_to"].isoformat() if filters["pub_date_to"] else ""
                ),
                "group_by": filters["group_by"],
            },
            "query_string": request.GET.urlencode(),
        },
    )


def data_availability_report_options(request):
    """
    Opções dos filtros dependentes do relatório de data availability (JSON):
    periódicos da coleção e intervalo de datas de publicação online.
    """
    from article import reports

    filters = _get_data_availability_filters(request)
    return JsonResponse(
        reports.get_filter_options(filters["collection_acron"], filters["journal_id"])
    )


def _data_availability_report_csv(report):
    import csv

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        'attachment; filename="data_availability_report.csv"'
    )
    writer = csv.writer(response)
    header = ["year", "total"]
    for status, _label in report["columns"]:
        header.extend([status, f"{status} (%)"])
    writer.writerow(header)
    for row in report["rows"] + [dict(report["totals"], year="total")]:
        line = [row["year"] or "", row["total"]]
        for cell in row["cells"]:
            line.extend([cell["count"], cell["percent"]])
        writer.writerow(line)
    return response
