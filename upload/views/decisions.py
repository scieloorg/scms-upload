from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.users.permission_policies import TeamScopedEditView
from upload.authorization import user_can_act_on_package
from upload.models import choices
from upload.permissions import ASSIGN_PACKAGE, PUBLISH_PACKAGE, REQUEST_CORRECTION
from upload.querysets import get_scoped_package_queryset
from upload.tasks import task_upload_workflow_publish_article


class PackageDecisionMixin:
    success_message = _("Decision recorded successfully")
    error_message = _("Unable to complete the operation. Check the form and try again.")
    permission_error_message = _("Operation not available")

    def get_success_url(self):
        return reverse("wagtailsnippets_upload_package:inspect", args=[self.object.pk])

    def get_task_function(self):
        return task_upload_workflow_publish_article

    def process_decision(self, package, user, force_journal, force_issue):
        return package.process_qa_decision(
            user, self.get_task_function(), force_journal, force_issue
        )

    def form_valid(self, form):
        decision = form.cleaned_data.get("qa_decision")
        if decision == choices.PS_PENDING_CORRECTION:
            permission = REQUEST_CORRECTION
        elif decision == choices.PS_PENDING_QA_DECISION:
            permission = ASSIGN_PACKAGE
        else:
            permission = PUBLISH_PACKAGE
        if not user_can_act_on_package(self.request.user, permission, form.instance):
            messages.error(self.request, self.permission_error_message)
            return HttpResponseRedirect(self.get_success_url())

        package = form.save_all(self.request.user)

        force_journal_publication = form.cleaned_data.get("force_journal_publication")
        if permission == PUBLISH_PACKAGE and not package.journal:
            messages.error(
                self.request,
                _(
                    "Package journal was not identified in the system or is not registered"
                ),
            )
            return HttpResponseRedirect(self.get_success_url())

        force_issue_publication = form.cleaned_data.get("force_issue_publication")
        if permission == PUBLISH_PACKAGE and not package.issue:
            messages.error(
                self.request,
                _(
                    "Package issue was not identified in the system or is not registered"
                ),
            )
            return HttpResponseRedirect(self.get_success_url())

        if self.process_decision(
            package,
            self.request.user,
            force_journal_publication,
            force_issue_publication,
        ):
            messages.success(self.request, self.success_message)
            return HttpResponseRedirect(self.get_success_url())
        messages.error(self.request, self.error_message)
        return self.form_invalid(form)


class QAPackageEditView(PackageDecisionMixin, TeamScopedEditView):
    pass


class ReadyToPublishPackageEditView(PackageDecisionMixin, TeamScopedEditView):
    pass


def assign(request):
    package_id = request.GET.get("package_id")
    user = request.user

    if not user.has_perm(f"upload.{ASSIGN_PACKAGE}"):
        messages.error(request, _("You do not have permission to assign packages."))
        return redirect("wagtailsnippets_upload_package:list")

    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("wagtailsnippets_upload_package:list")

    get_object_or_404(
        get_scoped_package_queryset(request.user, ASSIGN_PACKAGE), pk=package_id
    )

    return redirect("wagtailsnippets_upload_qapackage:edit", pk=package_id)
