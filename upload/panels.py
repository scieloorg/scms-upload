from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtailautocomplete.edit_handlers import AutocompletePanel




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
                    "reviewer", attrs={"data-upload-decision-target": "reviewer"}
                ),
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
