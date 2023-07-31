from django.db import models
from django.utils.translation import gettext as _

from core.models import CommonControlField
from location.forms import CityForm, CountryForm, LocationForm, StateForm


class City(CommonControlField):
    """
    Represent a list of cities

    Fields:
        name
    """

    name = models.TextField(_("City Name"))

    class Meta:
        verbose_name = _("City")
        verbose_name_plural = _("Cities")

    def __unicode__(self):
        return "%s" % self.name

    def __str__(self):
        return "%s" % self.name

    @classmethod
    def get(cls, name):
        if name:
            return cls.objects.get(name=name)

    @classmethod
    def get_or_create(cls, user, name):
        try:
            return cls.get(name=name)
        except cls.DoesNotExist:
            city = City()
            city.name = name
            city.creator = user
            city.save()
            return city

    @property
    def data(self):
        return dict(
            city__name=self.name,
        )

    base_form_class = CityForm


class State(CommonControlField):
    """
    Represent the list of states

    Fields:
        name
        acronym
    """

    name = models.TextField(_("State Name"), blank=True, null=True)
    acronym = models.CharField(
        _("State Acronym"), blank=True, null=True, max_length=255
    )

    class Meta:
        verbose_name = _("State")
        verbose_name_plural = _("States")

    def __unicode__(self):
        return "%s %s" % (self.name, self.acronym)

    def __str__(self):
        return "%s %s" % (self.name, self.acronym)

    @classmethod
    def get(cls, name=None, acronym=None):
        if acronym:
            return cls.objects.get(acronym=acronym)
        if name:
            return cls.objects.get(name__iexact=name)

    @classmethod
    def get_or_create(cls, user, name=None, acronym=None):
        try:
            return cls.get(name, acronym)
        except cls.DoesNotExist:
            if not name and not acronym:
                raise ValueError("State.get_or_create requires name or acronym")
            state = State()
            state.name = name
            state.acronym = acronym
            state.creator = user
            state.save()
            return state

    @property
    def data(self):
        return dict(
            state__name=self.name,
            state__acronym=self.acronym,
        )

    base_form_class = StateForm


class Country(CommonControlField):
    """
    Represent the list of Countries

    Fields:
        name
        acronym
    """

    name = models.TextField(_("Country Name"), blank=True, null=True)
    acronym = models.CharField(
        _("Country Acronym"), blank=True, null=True, max_length=255
    )

    class Meta:
        verbose_name = _("Country")
        verbose_name_plural = _("Countries")

    def __unicode__(self):
        return "%s %s" % (self.name, self.acronym)

    def __str__(self):
        return "%s %s" % (self.name, self.acronym)

    @classmethod
    def get(cls, name=None, acronym=None):
        if acronym:
            return cls.objects.get(acronym=acronym)
        if name:
            return cls.objects.get(name__iexact=name)

    @classmethod
    def get_or_create(cls, user, name=None, acronym=None):
        try:
            return cls.get(name, acronym)
        except cls.DoesNotExist:
            if not name and not acronym:
                raise ValueError("Country.get_or_create requires name or acronym")
            country = Country()
            country.name = name
            country.acronym = acronym
            country.creator = user
            country.save()
            return country

    @property
    def data(self):
        return dict(
            country__name=self.name,
            country__acronym=self.acronym,
        )

    base_form_class = CountryForm


class Location(CommonControlField):
    city = models.ForeignKey(
        City,
        verbose_name=_("City"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    state = models.ForeignKey(
        State,
        verbose_name=_("State"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    country = models.ForeignKey(
        Country,
        verbose_name=_("Country"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Location")
        verbose_name_plural = _("Locations")

    def __unicode__(self):
        return "%s | %s | %s" % (self.country, self.state, self.city)

    def __str__(self):
        return "%s | %s | %s" % (self.country, self.state, self.city)

    @classmethod
    def get(cls, country, state, city):
        return cls.objects.get(country=country, state=state, city=city)

    @classmethod
    def get_or_create(cls, user, country, state, city):
        try:
            return cls.get(country=country, state=state, city=city)
        except cls.DoesNotExist:
            location = Location()
            location.country = country
            location.state = state
            location.city = city
            location.creator = user
            location.save()
            return location

    @property
    def data(self):
        d = {}
        d.update(self.city.data)
        d.update(self.state.data)
        d.update(self.country.data)
        return d

    base_form_class = LocationForm
