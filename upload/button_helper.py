from django.urls import reverse
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.helpers import ButtonHelper

from . import choices


class UploadButtonHelper(ButtonHelper):
    index_button_classnames = ["button", "button-small", "button-secondary"]
    btn_default_classnames = [
        "button-small",
        "icon",
    ]

    def get_buttons_for_obj(
        self, obj, exclude=None, classnames_add=None, classnames_exclude=None
    ):
        """
        This function is used to gather all available buttons.
        We append our custom button to the btns list.
        """
        ph = self.permission_helper
        usr = self.request.user
        url_name = self.request.resolver_match.url_name

        print(f"urlname: {url_name}")

        analyst_team_member = ph.user_is_analyst_team_member(usr, obj)

        exclude = ["delete"]
        if analyst_team_member:
            if obj.status in (
                choices.PS_SUBMITTED,
                choices.PS_ENQUEUED_FOR_VALIDATION,
                choices.PS_VALIDATED_WITH_ERRORS,
                choices.PS_PENDING_QA_DECISION,
                choices.PS_PENDING_CORRECTION,
                choices.PS_UNEXPECTED,
                choices.PS_PUBLISHED,
                choices.PS_REQUIRED_ERRATUM,
                choices.PS_REQUIRED_UPDATE,
                choices.PS_ARCHIVED,
            ):
                exclude.append("edit")
        else:
            # usuário sem poder de análise
            exclude.append("edit")
        if url_name.endswith("_modeladmin_inspect"):
            exclude.append("inspect")

        btns = super().get_buttons_for_obj(
            obj, exclude, classnames_add, classnames_exclude
        )

        if not obj.is_validation_finished:
            return btns

        classnames = []
        if url_name.endswith("_modeladmin_inspect"):
            classnames.extend(ButtonHelper.inspect_button_classnames)
        if url_name.endswith("_modeladmin_index"):
            classnames.extend(UploadButtonHelper.index_button_classnames)

        self.add_finish_deposit_button(btns, obj, classnames, url_name)

        if analyst_team_member:
            self.add_assign_button(btns, obj, classnames)
            self.add_archive_button(btns, obj, classnames)
        return btns

    def add_assign_button(self, btns, obj, classnames, label=None):
        status = (
            choices.PS_PENDING_QA_DECISION,
            choices.PS_VALIDATED_WITH_ERRORS,
        )
        if obj.status in status:
            text = label or _("Accept / Reject the package or delegate it")
            btns.append({
                "url": reverse("upload:assign") + "?package_id=%s" % str(obj.id),
                "label": text,
                "classname": self.finalise_classname(classnames),
                "title": text,
            })

    def add_finish_deposit_button(self, btns, obj, classnames, url_name):
        status = (
            choices.PS_VALIDATED_WITH_ERRORS,
        )
        if obj.status in status and url_name == "upload_package_modeladmin_inspect":
            text = _("Finish deposit")
            btns.append({
                "url": reverse("upload:finish_deposit") + "?package_id=%s" % str(obj.id),
                "label": text,
                "classname": self.finalise_classname(classnames),
                "title": text,
            })

    def add_archive_button(self, btns, obj, classnames, label=None):
        status = (
            choices.PS_UNEXPECTED,
        )
        if obj.status in status:
            text = label or _("Archive")
            btns.append({
                "url": reverse("upload:archive_package") + "?package_id=%s" % str(obj.id),
                "label": text,
                "classname": self.finalise_classname(classnames),
                "title": text,
            })
