from django.urls import path

from article.views import download_package

app_name = "article"

urlpatterns = [
    path("download-package", view=download_package, name="download_package"),
]
