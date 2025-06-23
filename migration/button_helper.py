from django.utils.translation import gettext as _
from wagtail_modeladmin.helpers import ButtonHelper


class MigrationFailureButtonHelper(ButtonHelper):
    btn_default_classnames = [
        "button-small",
        "icon",
    ]

    def view_migration_failure(self, obj):
        text = _("View migration failure")
        return {
            "url": "",
            "label": text,
            "classname": self.finalise_classname(self.btn_default_classnames),
            "title": text,
        }

    def get_buttons_for_obj(
        self, obj, exclude=None, classnames_add=None, classnames_exclude=None
    ):
        """
        This function is used to gather all available buttons.
        We append our custom button to the btns list.
        """
        btns = super().get_buttons_for_obj(
            obj, exclude, classnames_add, classnames_exclude
        )

        btns.append(self.view_migration_failure(obj))
        return btns
