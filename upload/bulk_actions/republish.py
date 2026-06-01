from django.utils.functional import classproperty
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from wagtail.snippets.bulk_actions.snippet_bulk_action import SnippetBulkAction


class BaseRepublishBulkAction(SnippetBulkAction):
    """Classe base — não registrar diretamente."""

    website_kind: str

    template_name = "upload/bulk_actions/confirm_bulk_republish.html"
    action_priority = 50

    @classproperty
    def models(cls):
        from upload.models import ReadyToPublishPackage
        return [ReadyToPublishPackage]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["website_kind"] = self.website_kind
        return context

    def get_execution_context(self):
        return {
            **super().get_execution_context(),
            "website_kind": self.website_kind,
            "request": self.request,   # ← necessário para user_id/username
        }

    @classmethod
    def execute_action(cls, objects, website_kind=None, request=None, **kwargs):
        from upload.tasks import task_republish_articles

        package_ids = [obj.pk for obj in objects]

        task_republish_articles.delay(
            username=request.user.username,
            user_id=request.user.id,
            website_kind=website_kind,
            package_ids=package_ids,
        )
        return len(objects), 0

    def get_success_message(self, num_parent_objects, num_child_objects):
        return ngettext(
            "%(count)d pacote enviado para republicação (%(website_kind)s).",
            "%(count)d pacotes enviados para republicação (%(website_kind)s).",
            num_parent_objects,
        ) % {
            "count": num_parent_objects,
            "website_kind": self.website_kind,
        }


class RepublishQABulkAction(BaseRepublishBulkAction):
    display_name = _("Republish QA")
    action_type = "republish_qa"
    aria_label = _("Republish selected packages on QA")
    website_kind = "QA"


class RepublishPublicBulkAction(BaseRepublishBulkAction):
    display_name = _("Republish Public")
    action_type = "republish_public"
    aria_label = _("Republish selected packages on Public")
    website_kind = "PUBLIC"