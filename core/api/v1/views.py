from rest_framework import viewsets

from core.models import PressRelease
from core.validators import validate_params


class GenericIssueViewSet(viewsets.ModelViewSet):
    serializer_class = PressRelease
    http_method_names = ["get"]
    queryset = PressRelease.objects.all()


class PressReleaseViewSet(GenericIssueViewSet):
    def get_queryset(self):
        queryset = super().get_queryset()
        journal_acronym = self.request.query_params.get("acronym")

        validate_params(self.request, "acronym", "")
        custom_queryset = queryset.filter(acronym=journal_acronym)
        return custom_queryset if journal_acronym else queryset
