from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.helpers import ButtonHelper

from article.choices import AS_REQUIRE_ERRATUM, AS_REQUIRE_UPDATE


class RequestArticleChangeButtonHelper(ButtonHelper):
    index_button_classnames = ["button", "button-small", "button-secondary"]

    def see_instructions(self, obj, classnames):
        text = _("See instructions")

        return {
            "url": "/admin/article/article/inspect/%s/" % str(obj.article.id),
            "label": text,
            "classname": self.finalise_classname(classnames),
            "title": text,
        }

    def submit_change(self, obj, classnames):
        text = _("Submit change")

        package_category = ""
        # FIXME
        # if obj.article.status == AS_REQUIRE_UPDATE:
        #     package_category = PC_UPDATE
        # elif obj.article.status == AS_REQUIRE_ERRATUM:
        #     package_category = PC_ERRATUM

        return {
            "url": "/admin/upload/package/create/?article_id=%s&package_category=%s"
            % (obj.article.id, package_category),
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
        if url_name.endswith("_modeladmin_inspect"):
            classnames.extend(ButtonHelper.inspect_button_classnames)
        if url_name.endswith("_modeladmin_index"):
            classnames.extend(ArticleButtonHelper.index_button_classnames)

        # if ph.user_can_make_article_change(usr, obj.article) and obj.article.status in (
        #     AS_REQUIRE_ERRATUM,
        #     AS_REQUIRE_UPDATE,
        # ):
        #     if obj.demanded_user == usr:
        #         btns.append(self.submit_change(obj, classnames))
        #         btns.append(self.see_instructions(obj, classnames))

        return btns


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

    def submit_change(self, obj, classnames):
        text = _("Submit change")

        package_category = ""
        # FIXME
        # if obj.article.status == AS_REQUIRE_UPDATE:
        #     package_category = PC_UPDATE
        # elif obj.article.status == AS_REQUIRE_ERRATUM:
        #     package_category = PC_ERRATUM

        return {
            "url": "/admin/upload/package/create/?article_id=%s&package_category=%s"
            % (obj.id, package_category),
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
        if url_name == "article_article_modeladmin_inspect":
            classnames.extend(ButtonHelper.inspect_button_classnames)
        if url_name == "article_article_modeladmin_index":
            classnames.extend(ArticleButtonHelper.index_button_classnames)

        # if ph.user_can_request_article_change(usr, obj) and obj.status not in (
        #     AS_REQUIRE_UPDATE,
        #     AS_REQUIRE_ERRATUM,
        # ):
        #     btns.append(self.request_change(obj, classnames))

        # if ph.user_can_make_article_change(usr, obj) and obj.status in (
        #     AS_REQUIRE_ERRATUM,
        #     AS_REQUIRE_UPDATE,
        # ):
        #     for rac in obj.requestarticlechange_set.all():
        #         if rac.demanded_user == usr:
        #             btns.append(self.submit_change(obj, classnames))
        #             break

        return btns
