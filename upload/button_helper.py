from django.urls import reverse
from django.utils.translation import gettext as _

from wagtail.contrib.modeladmin.helpers import ButtonHelper

from . import choices


class UploadButtonHelper(ButtonHelper):
    index_button_classnames = ["button", "button-small", "button-secondary"]
    btn_default_classnames = ["button-small", "icon",]

    def assign(self, obj, classnames, label=None):
        text = label or _("Assign")
        return {
            "url": reverse("upload:assign") + "?package_id=%s" % str(obj.id),
            "label": text,
            "classname": self.finalise_classname(classnames),
            "title": text,
        }

    def finish_deposit_button(self, obj, classnames):
        text = _("Finish deposit")
        return {
            "url": reverse("upload:finish_deposit") + "?package_id=%s" % str(obj.id),
            "label": text,
            "classname": self.finalise_classname(classnames),
            "title": text,
        }

    def view_published_document(self, obj, classnames):
        # TODO: A URL deve ser configurada para ver o documento publicado
        text = _("View document")
        return {
            "url": "",
            "label": text,
            "classname": self.finalise_classname(classnames),
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

        ph = self.permission_helper
        usr = self.request.user
        url_name = self.request.resolver_match.url_name

        classnames = []
        if url_name.endswith('_modeladmin_inspect'):
            classnames.extend(ButtonHelper.inspect_button_classnames)
        if url_name.endswith('_modeladmin_index'):
            classnames.extend(UploadButtonHelper.index_button_classnames)

        if obj.status == choices.PS_READY_TO_BE_FINISHED and ph.user_can_finish_deposit(usr, obj) and url_name == 'upload_package_modeladmin_inspect':
            btns.append(self.finish_deposit_button(obj, classnames))

        if obj.status == choices.PS_PUBLISHED:
            btns.append(self.view_published_document(obj, classnames))

        if obj.assignee is None:
            if obj.status == choices.PS_QA and ph.user_can_assign_package(usr, obj):
                btns.append(self.assign(obj, classnames))
        elif obj.assignee != usr:
            btns.append(self.assign(obj, classnames, _('Reassign')))
            
        return btns
