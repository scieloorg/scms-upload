from django.utils.translation import gettext as _

from wagtail.contrib.modeladmin.helpers import ButtonHelper

from django.urls import reverse

from .choices import PackageStatus


class UploadButtonHelper(ButtonHelper):
    btn_default_classnames = ["button-small", "icon",]

    def accept_button(self, obj):
        text = _("Accept")
        return {
            "url": reverse("upload:accept") + "?package_id=%s" % str(obj.id),
            "label": text,
            "classname": self.finalise_classname(self.btn_default_classnames),
            "title": text,
        }

    def reject_button(self, obj):
        text = _("Reject")
        return {
            "url": reverse("upload:reject") + "?package_id=%s" % str(obj.id),
            "label": text,
            "classname": self.finalise_classname(self.btn_default_classnames),
            "title": text,
        }

    def validate_button(self, obj):
        text = _("Validate")
        return {
            "url": reverse("upload:validate") + "?package_id=%s" % str(obj.id),
            "label": text,
            "classname": self.finalise_classname(self.btn_default_classnames),
            "title": text,
        }

    def preview_button(self, obj):
        text = _("Preview")
        return {
            "url": reverse("upload:preview") + "?package_id=%s" % str(obj.id),
            "label": text,
            "classname": self.finalise_classname(self.btn_default_classnames),
            "title": text,
        }

    def publish_button(self, obj):
        text = _("Publish")
        return {
            "url": reverse("upload:publish") + "?package_id=%s" % str(obj.id),
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

        if obj.status == int(PackageStatus.SUBMITTED) and ph.user_can_accept(usr, obj):    
            btns.append(self.accept_button(obj))

        if obj.status in [
            int(x) for x in [
                PackageStatus.SUBMITTED, PackageStatus.ACCEPTED,
                PackageStatus.VALIDATED_WITH_ERRORS, 
                PackageStatus.VALIDATED_WITHOUT_ERRORS,
                PackageStatus.SCHEDULED_FOR_PUBLICATION,
            ]
        ] and ph.user_can_reject(usr, obj):
            btns.append(self.reject_button(obj))

        if obj.status == int(PackageStatus.ACCEPTED) and ph.user_can_validate(usr, obj):
            btns.append(self.validate_button(obj))

        if ph.user_can_preview(usr, obj):
            btns.append(self.preview_button(obj))

        if obj.status in [
            int(x) for x in [
                PackageStatus.ACCEPTED,
                PackageStatus.ENQUEUED_FOR_VALIDATION,
                PackageStatus.VALIDATED_WITH_ERRORS,
                PackageStatus.VALIDATED_WITHOUT_ERRORS,
            ]
        ] and ph.user_can_publish(usr, obj):
            btns.append(self.publish_button(obj))          

        return btns
