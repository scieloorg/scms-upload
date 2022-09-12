from django.utils.translation import gettext as _

from wagtail.contrib.modeladmin.helpers import ButtonHelper


class ArticleButtonHelper(ButtonHelper):
    index_button_classnames = ["button", "button-small", "button-secondary"]

    def request_change(self, obj, classnames):
        text = _("Request change")
        return {
            "url": "/admin/article/requestarticlechange/create/?article_id=%s" % obj.id,
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
        if ph.user_can_request_article_change(usr, obj):
            if url_name == 'article_article_modeladmin_inspect':
                classnames.extend(ButtonHelper.inspect_button_classnames)

            if url_name == 'article_article_modeladmin_index':
                classnames.extend(ArticleButtonHelper.index_button_classnames)

            btns.append(self.request_change(obj, classnames))

        return btns
