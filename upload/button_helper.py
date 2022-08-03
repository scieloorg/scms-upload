from django.utils.translation import gettext as _

from wagtail.contrib.modeladmin.helpers import ButtonHelper

from django.urls import reverse

from .choices import PackageStatus


class UploadButtonHelper(ButtonHelper):
    btn_default_classnames = ["button-small", "icon",]

    def finish_deposit_button(self, obj):
        text = _("Finish deposit")
        return {
            "url": reverse("upload:finish_deposit") + "?package_id=%s" % str(obj.id),
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

        ph = self.permission_helper
        usr = self.request.user
        url_name = self.request.resolver_match.url_name

        if obj.status != int(PackageStatus.FINISHED) and ph.user_can_finish_deposit(usr, obj):
            btns.append(self.finish_deposit_button(obj))
            
        return btns
