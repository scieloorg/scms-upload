from django.contrib.auth.models import AbstractUser
from django.db.models import CharField, Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Default custom user model for SciELO Content Manager .
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    #: First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = CharField(max_length=150, blank=True, verbose_name="first name")
    last_name = CharField(max_length=150, blank=True, verbose_name="last name")

    def get_absolute_url(self):
        """Get url for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})

    # autocomplete_search_field = "username"

    def autocomplete_label(self):
        if self.name:
            return self.name
        if self.first_name or self.last_name:
            return f"{self.first_name} {self.last_name}"
        if self.email:
            return self.email
        if self.username:
            return self.username

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return User.objects.filter(
            Q(username__icontains=text) |
            Q(email__icontains=text) |
            Q(name__icontains=text))
