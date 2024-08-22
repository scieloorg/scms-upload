from wagtail.admin.forms import WagtailAdminModelForm
from django.utils.translation import gettext as _

from core.forms import CoreAdminModelForm
from article import choices


class ArticleForm(CoreAdminModelForm):
    def save_all(self, user):
        article = super().save_all(user)

        for dwl in article.doi_with_lang.all():
            dwl.creator = user

        for t in article.title_with_lang.all():
            t.creator = user

        self.save()

        return article


class RelatedItemForm(CoreAdminModelForm):
    def save_all(self, user):
        related_item = super().save_all(user)

        self.save()

        return related_item


class RequestArticleChangeForm(CoreAdminModelForm):
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            article = cleaned_data.get("article")
            comment = cleaned_data.get("comment")
            change_type = cleaned_data.get("change_type")

            if not article:
                self.add_error(
                    "article",
                    _("Inform the article that needs to be changed"),
                )
            if not comment:
                self.add_error(
                    "comment",
                    _("Comment what needs to be changed"),
                )
            if not change_type:
                self.add_error(
                    "change_type",
                    _("Inform the type of change"),
                )

    def save_all(self, user):
        request_article_change = super().save_all(user)
        article = request_article_change
        if request_article_change.change_type == choices.RCT_ERRATUM:
            article.status = choices.AS_REQUIRE_ERRATUM
        elif request_article_change.change_type == choices.RCT_UPDATE:
            article.status = choices.AS_REQUIRE_UPDATE
        article.save()

        return request_article_change
