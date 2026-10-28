from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from wagtail.snippets.bulk_actions.snippet_bulk_action import SnippetBulkAction

from upload import choices
from upload.models import ReadyToPublishPackage
from upload.permissions import REPUBLISH_PACKAGE
from upload.querysets import get_scoped_package_queryset
from upload.tasks import task_republish_articles


class BaseRepublishBulkAction(SnippetBulkAction):
    """Classe base — não registrar diretamente."""

    template_name = "upload/bulk_actions/confirm_bulk_republish.html"
    action_priority = 50

    models = [ReadyToPublishPackage]

    def check_perm(self, obj):
        return (
            get_scoped_package_queryset(self.request.user, REPUBLISH_PACKAGE)
            .filter(pk=obj.pk)
            .exists()
        )

    def get_actionable_objects(self):
        objects, denied = super().get_actionable_objects()
        if denied["items_with_no_access"]:
            raise PermissionDenied

        return objects, denied

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["website_kind"] = self.website_kind
        context["website_kind_label"] = choices.WEBSITE_ENVIRONMENT_LABELS[
            self.website_kind
        ]

        return context

    def get_execution_context(self):
        return {
            **super().get_execution_context(),
            "website_kind": self.website_kind,
            "request": self.request,
        }

    @classmethod
    def execute_action(cls, objects, website_kind=None, request=None, **kwargs):
        package_ids = [obj.pk for obj in objects]
        if not package_ids:
            raise PermissionDenied

        authorized_ids = set(
            get_scoped_package_queryset(request.user, REPUBLISH_PACKAGE)
            .filter(pk__in=package_ids)
            .values_list("pk", flat=True)
        )
        if authorized_ids != set(package_ids):
            raise PermissionDenied

        task_republish_articles.delay(
            username=request.user.username,
            user_id=request.user.id,
            website_kind=website_kind,
            package_ids=package_ids,
        )

        return len(objects), 0

    def get_success_message(self, num_parent_objects, num_child_objects):
        return ngettext(
            "%(count)d package scheduled for republication (%(website_kind)s).",
            "%(count)d packages scheduled for republication (%(website_kind)s).",
            num_parent_objects,
        ) % {
            "count": num_parent_objects,
            "website_kind": choices.WEBSITE_ENVIRONMENT_LABELS[self.website_kind],
        }


class RepublishQABulkAction(BaseRepublishBulkAction):
    display_name = _("Republish QA")
    action_type = "republish_qa"
    aria_label = _("Republish selected packages on QA")
    website_kind = "QA"


class RepublishPublicBulkAction(BaseRepublishBulkAction):
    display_name = _("Republish in Production")
    action_type = "republish_public"
    aria_label = _("Republish selected packages in Production")
    website_kind = "PUBLIC"
