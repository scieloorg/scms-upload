from django.contrib.auth.models import AbstractUser
from django.db.models import CharField, ManyToManyField
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
    journal = ManyToManyField("journal.Journal", verbose_name=_("Journal"), blank=True)

    def get_absolute_url(self):
        """Get url for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})

    autocomplete_search_field = "username"

    def autocomplete_label(self):
        label = self.username
        user_groups = sorted([g.name for g in self.groups.all()])

        full_name = f"{self.first_name} {self.last_name}"
        if full_name != " ":
            label += f" ({full_name})"

        if len(user_groups) > 0:
            label += f" - {', '.join(user_groups)}"

        return label
