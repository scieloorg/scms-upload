from django.urls import path

from .views import request_change


app_name = "article"

urlpatterns = [
    path("request-change", view=request_change, name="request_change"),
]
