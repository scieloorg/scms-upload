from django.conf import settings
from rest_framework.routers import DefaultRouter, SimpleRouter

from core.api.v1.views import PressReleaseViewSet

app_name = "pid_provider"

if settings.DEBUG:
    router = DefaultRouter()
else:
    router = SimpleRouter()

router.register("pressrelease", PressReleaseViewSet, basename="press-release")


urlpatterns = router.urls