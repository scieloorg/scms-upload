from wagtail.admin.forms import WagtailAdminModelForm


class ArticleForm(WagtailAdminModelForm):

    def save_all(self, user):
        article = super().save(commit=False)
        article.creator = user

        self.save()

        return article
