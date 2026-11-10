from django.urls import reverse
from wagtail.admin.ui.tables import Column, TitleColumn
from wagtail.admin.widgets import ListingButton

from upload.admin_buttons import get_package_action_buttons, get_package_website_links


class DocumentTitleColumn(TitleColumn):
    cell_template_name = "upload/documents/title_cell.html"


class PublicationColumn(Column):
    cell_template_name = "upload/documents/publication_cell.html"

    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        context["publication_document_url"] = reverse(
            "wagtailsnippets_upload_package:inspect", args=[instance.pk]
        )
        context["qa_publication"] = instance.publication_situation("QA")
        context["public_publication"] = instance.publication_situation("PUBLIC")
        context["website_urls"] = {
            website["label"]: website["url"]
            for website in get_package_website_links(instance)
        }

        return context


class DocumentUpdatedColumn(Column):
    cell_template_name = "upload/documents/updated_cell.html"


class DocumentActionsColumn(Column):
    cell_template_name = "upload/documents/actions_cell.html"

    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        context["actions"] = get_package_action_buttons(
            context["request"].user,
            instance,
            ListingButton,
            include_finish_deposit=True,
        )

        return context


class SubmissionTitleColumn(TitleColumn):
    def get_link_url(self, instance, parent_context):
        return (
            reverse("wagtailsnippets_upload_package:list")
            + f"?pkg_zip_id={instance.pk}"
        )


class SubmissionActionsColumn(Column):
    cell_template_name = "upload/submissions/actions_cell.html"
