from django.urls import reverse
from wagtail.admin.ui.tables import Column, TitleColumn
from wagtail.admin.widgets import ListingButton

from upload.admin_buttons import get_package_action_buttons, get_package_website_links
from upload.publication_status import publication_situation


class DocumentTitleColumn(TitleColumn):
    cell_template_name = "upload/documents/title_cell.html"


class PublicationColumn(Column):
    cell_template_name = "upload/documents/publication_cell.html"

    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        context["qa_publication"] = publication_situation(instance, "QA")
        context["public_publication"] = publication_situation(instance, "PUBLIC")

        return context


class DocumentUpdatedColumn(Column):
    cell_template_name = "upload/documents/updated_cell.html"


class DocumentActionsColumn(Column):
    cell_template_name = "upload/documents/actions_cell.html"

    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        context["report_url"] = reverse(
            "wagtailsnippets_upload_package:inspect", args=[instance.pk]
        )
        context["actions"] = get_package_action_buttons(
            context["request"].user,
            instance,
            ListingButton,
            include_finish_deposit=True,
        )
        context["websites"] = get_package_website_links(instance)

        return context


class SubmissionActionsColumn(Column):
    cell_template_name = "upload/submissions/actions_cell.html"

    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        context["documents_url"] = (
            reverse("wagtailsnippets_upload_package:list")
            + f"?pkg_zip_id={instance.pk}"
        )

        return context
