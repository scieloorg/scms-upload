from django.utils.functional import cached_property
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtailautocomplete.edit_handlers import AutocompletePanel


class ReportTitlePanel(FieldPanel):
    class BoundPanel(FieldPanel.BoundPanel):
        @cached_property
        def value_from_instance(self):
            return self.instance.display_title()


class ReportFilePanel(FieldPanel):
    def format_value_for_display(self, value):
        if not value:
            return super().format_value_for_display(value)

        return format_html('<a href="{}">{}</a>', value.url, _("Download report"))


class DecisionPanel(MultiFieldPanel):
    class BoundPanel(MultiFieldPanel.BoundPanel):
        class Media:
            js = ["upload/js/decision.js"]


def decision_panels():
    return [
        DecisionPanel(
            [
                FieldPanel("qa_decision"),
                FieldPanel(
                    "correction_assignee",
                    attrs={"data-upload-decision-target": "corrections"},
                ),
                FieldPanel(
                    "qa_comment",
                    attrs={"data-upload-decision-target": "comment"},
                ),
                MultiFieldPanel(
                    [
                        FieldPanel("force_journal_publication"),
                        FieldPanel("force_issue_publication"),
                        FieldPanel("order"),
                        AutocompletePanel("linked"),
                    ],
                    heading=_("Publication options"),
                    attrs={"data-upload-decision-target": "publication"},
                ),
            ],
            attrs={"data-controller": "upload-decision"},
        )
    ]
