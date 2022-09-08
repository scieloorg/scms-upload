from wagtail.admin.forms import WagtailAdminModelForm


class ArticleForm(WagtailAdminModelForm):

    def save_all(self, user):        
        article = super().save(commit=False)
        article.creator = user

        for dwl in article.doi_with_lang.all():
            dwl.creator = user

        for a in article.author.all():
            a.creator = user

        for t in article.title_with_lang.all():
            t.creator = user

        for ri in article.related_item.all():
            ri.creator = user

        self.save()

        return article
