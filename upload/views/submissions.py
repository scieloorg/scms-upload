from functools import partial

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail.snippets.views.snippets import CreateView

from upload.tasks import task_receive_packages


class PackageZipCreateView(CreateView):
    def form_valid(self, form):
        if not self.permission_policy.user_has_permission(
            self.request.user,
            "add",
        ):
            messages.error(
                self.request,
                _("Operation not available"),
            )
            return HttpResponseRedirect(self.get_success_url())

        pkg_zip = form.save_all(self.request.user)
        transaction.on_commit(
            partial(
                task_receive_packages.apply_async,
                kwargs=dict(
                    user_id=self.request.user.id,
                    pkg_zip_id=pkg_zip.id,
                ),
            )
        )
        documents_url = reverse("wagtailsnippets_upload_package:list")
        messages.success(
            self.request,
            format_html(
                '{} <a href="{}?pkg_zip_id={}">{}</a>',
                _(
                    "Package received. Processing runs in the background. "
                    "Follow its progress in Documents."
                ),
                documents_url,
                pkg_zip.pk,
                _("View documents"),
            ),
        )

        return HttpResponseRedirect(self.get_success_url())
