from django.urls import path

from .views import validate, preview, publish, accept, reject


app_name = "upload"

urlpatterns = [
    path("accept", view=accept, name="accept"),
    path("reject", view=reject, name="reject"),
    path("validate", view=validate, name="validate"),
    path("preview", view=preview, name="preview"),
    path("publish", view=publish, name="publish")
]
