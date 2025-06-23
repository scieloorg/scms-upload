from wagtail_modeladmin.helpers import PermissionHelper

MAKE_ARTICLE_CHANGE = "make_article_change"
REQUEST_ARTICLE_CHANGE = "request_article_change"


class ArticlePermissionHelper(PermissionHelper):
    def user_can_make_article_change(self, user, obj):
        return self.user_has_specific_permission(user, MAKE_ARTICLE_CHANGE)

    def user_can_request_article_change(self, user, obj):
        return self.user_has_specific_permission(user, REQUEST_ARTICLE_CHANGE)
