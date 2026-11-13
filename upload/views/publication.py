from functools import partial

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from collection.choices import WEBSITE_KIND
from upload.models import Package, UploadProcResult, choices
from upload.permissions import PUBLISH_PACKAGE, REPUBLISH_PACKAGE
from upload.publication_status import (
    PUBLICATION_ATTEMPT_PREFIX,
    PUBLICATION_FAILED,
    PUBLICATION_QUEUED,
    publication_situation,
)
from upload.querysets import get_scoped_package_queryset
from upload.tasks import task_republish_articles, task_upload_workflow_publish_article


@transaction.atomic
def retry_publication(request):
    if not request.user.has_perm(f"upload.{PUBLISH_PACKAGE}"):
        messages.error(request, _("Operation not available"))
        return redirect("wagtailsnippets_upload_package:list")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    package = get_object_or_404(
        Package.objects.filter(
            pk__in=get_scoped_package_queryset(request.user, PUBLISH_PACKAGE).values(
                "pk"
            ),
        ).select_for_update(),
        pk=package_id,
    )
    destination = reverse("wagtailsnippets_upload_package:inspect", args=[package.pk])
    purpose = "PUBLIC" if package.status == choices.PS_READY_TO_PUBLISH else "QA"
    if (
        package.status not in (choices.PS_READY_TO_PREVIEW, choices.PS_READY_TO_PUBLISH)
        or publication_situation(package, purpose)["state"] != PUBLICATION_FAILED
    ):
        messages.error(
            request, _("No failed publication attempt is available to retry.")
        )
        return redirect(destination)

    if request.method != "POST":
        return render(
            request,
            "upload/admin/package/confirm_action.html",
            {
                "title": _("Retry publication"),
                "message": _(
                    "Retry the failed publication using the existing authorization. "
                    "The document and its validation results will be preserved."
                ),
                "submit_label": _("Retry publication"),
                "package": package,
                "cancel_url": destination,
            },
        )

    attempt = UploadProcResult.create(
        request.user,
        package,
        f"{PUBLICATION_ATTEMPT_PREFIX} {[purpose]}",
    )
    attempt.detail = {"state": PUBLICATION_QUEUED, "websites": [purpose]}
    attempt.save(update_fields=["detail"])
    transaction.on_commit(
        partial(
            task_upload_workflow_publish_article.apply_async,
            kwargs={
                "user_id": request.user.pk,
                "username": request.user.username,
                "upload_package_id": package.pk,
                "websites": [purpose],
            },
        )
    )
    messages.success(request, _("Publication retry scheduled."))
    return redirect(destination)


def republish_selected(request):
    """
    Agenda republicação de um conjunto específico de pacotes selecionados na listagem.
    Os IDs dos pacotes chegam via GET (parâmetro package_ids, separados por vírgula)
    na primeira exibição do formulário, e via POST (campo oculto) na confirmação.
    """
    if not request.user.has_perm(f"upload.{REPUBLISH_PACKAGE}"):
        messages.error(request, _("Operation not available"))
        return redirect("wagtailsnippets_upload_package:list")

    if request.method == "POST":
        website_kind = request.POST.get("website_kind") or None
        package_ids_raw = request.POST.get("package_ids", "")
        package_ids = [
            int(pk) for pk in package_ids_raw.split(",") if pk.strip().isdigit()
        ]

        if not package_ids:
            messages.error(request, _("No packages selected."))
            return redirect("wagtailsnippets_upload_package:list")

        scoped_ids = set(
            get_scoped_package_queryset(request.user, REPUBLISH_PACKAGE)
            .filter(pk__in=package_ids)
            .values_list("pk", flat=True)
        )
        if scoped_ids != set(package_ids):
            messages.error(request, _("One or more packages are outside your scope."))
            return redirect("wagtailsnippets_upload_package:list")

        task_republish_articles.delay(
            username=request.user.username,
            user_id=request.user.id,
            website_kind=website_kind,
            package_ids=package_ids,
        )
        messages.success(
            request,
            _(
                "Batch republication of %(count)d package(s) scheduled for %(website)s website."
            )
            % {"count": len(package_ids), "website": website_kind or _("all")},
        )
        return redirect("wagtailsnippets_upload_package:list")

    package_ids_raw = request.GET.get("package_ids", "")
    package_ids = [pk for pk in package_ids_raw.split(",") if pk.strip().isdigit()]

    if not package_ids:
        messages.error(request, _("No packages selected."))
        return redirect("wagtailsnippets_upload_package:list")

    scoped_ids = set(
        get_scoped_package_queryset(request.user, REPUBLISH_PACKAGE)
        .filter(pk__in=package_ids)
        .values_list("pk", flat=True)
    )
    if scoped_ids != {int(pk) for pk in package_ids}:
        messages.error(request, _("One or more packages are outside your scope."))
        return redirect("wagtailsnippets_upload_package:list")

    return render(
        request,
        "upload/admin/package/republish_selected.html",
        {
            "website_kinds": WEBSITE_KIND,
            "package_ids": ",".join(package_ids),
            "package_count": len(package_ids),
        },
    )
