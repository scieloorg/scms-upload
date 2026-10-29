from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.forms import CoreAdminModelForm
from core.users.scoped_queryset import scope_by_membership


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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.for_user or not self.for_user.is_superuser:
            for field_name in ("source_article", "target_article"):
                self.fields[field_name].queryset = scope_by_membership(
                    self.for_user,
                    self.fields[field_name].queryset,
                    journal_field="journal",
                )


class RequestArticleChangeForm(CoreAdminModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._existing_pk = self.instance.pk

        if not self.for_user or not self.for_user.is_superuser:
            self.fields["article"].queryset = scope_by_membership(
                self.for_user,
                self.fields["article"].queryset,
                journal_field="journal",
            )

        for name, field in self.fields.items():
            if self._existing_pk or name in ("status", "submission"):
                field.disabled = True

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("article"):
            self.add_error("article", _("Inform the article that needs to be changed"))
        if not (cleaned_data.get("comment") or "").strip():
            self.add_error("comment", _("Comment what needs to be changed"))
        if not cleaned_data.get("change_type"):
            self.add_error("change_type", _("Inform the type of change"))
        return cleaned_data

    def save(self, commit=True):
        if not self.is_valid():
            raise ValueError(
                "The change request could not be saved because validation failed"
            )
        if self._existing_pk:
            # Never write a stale form instance over workflow state or history.
            self.instance = self._meta.model.objects.get(pk=self._existing_pk)
        else:
            if not commit:
                raise ValidationError(
                    _("Change requests must be saved through the request workflow")
                )
            self.instance = self._meta.model.request(
                self.for_user,
                self.cleaned_data["article"],
                self.cleaned_data["change_type"],
                self.cleaned_data["comment"],
            )
            self._existing_pk = self.instance.pk
        return self.instance

    def save_all(self, user):
        self.for_user = user
        return self.save()
