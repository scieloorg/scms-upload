from django.urls import path

from .views import finish_deposit


app_name = "upload"

urlpatterns = [
    path("finish", view=finish_deposit, name="finish_deposit"),
]
