from django.urls import path

from doi import views

app_name = "doi"

urlpatterns = [
    path(
        "deposit-article-doi/",
        view=views.deposit_article_doi,
        name="deposit_article_doi",
    ),
]
