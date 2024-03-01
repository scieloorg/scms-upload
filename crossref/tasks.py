import logging
import re


from article.models import Article
from config import celery_app
from core.utils.get_user import _get_user
from core.utils.requester import NonRetryableError, RetryableError
from crossref.models import (
    XMLCrossref,
    CrossrefConfiguration,
    CrossrefDOIDepositRecord,
    UserAccountCrossref,
)
from crossref.utils.utils import (
    generate_crossref_xml_from_article,
    verify_deposit_in_crossref,
)
from core.utils.requester import post_data


@celery_app.task(bind=True)
def generate_and_submit_crossref_xml_for_all_articles(
    self,
    prefix,
    user_id=None,
    username=None,
):
    try:
        data = CrossrefConfiguration.get_data(prefix=prefix)
    except CrossrefConfiguration.DoesNotExist:
        return None

    user = _get_user(user_id=user_id, username=username)
    # TODO
    #COLOCAR FILTRO PARA NAO PROCESSAR NOVAMENTE
    articles = Article.objects.filter(sps_pkg__isnull=False)

    for article in articles:
        create_or_update_xml_crossref.apply_async(
            kwargs=dict(
                xml_crossref=generate_crossref_xml_from_article(
                    article=article, data=data
                ),
                article_id=article.id,
                data=data,
                user=user,
            )
        )


@celery_app.task(bind=True)
def create_or_update_xml_crossref(
    self,
    xml_crossref,
    article_id,
    user,
):
    try:
        article = Article.objects.get(pk=article_id)
    except Article.DoesNotExist:
        logging.info(f"Not found {article_id}")
        return None

    XMLCrossref.create_or_update(
        file=xml_crossref,
        filename="crossref",
        article=article,
        user=user,
    )


@celery_app.task(bind=True)
def create_or_update_situation_crossref(self, xml, user_id, record=None):
    xml = CrossrefDOIDepositRecord.create_or_update(xml_crossref=xml)
    xml.status = record
    xml.save()


@celery_app.task(bind=True)
def post_xml_in_crossref(self, xml_crossref, username):
    url = "https://doi.crossref.org/servlet/deposit"
    try:
        account = UserAccountCrossref.objects.get(
            username=username,
        )
    except UserAccountCrossref.DoesNotExist:
        return None

    file_path = xml_crossref.file.path
    with open(file_path, "rb") as xml_file:
        files = {"file": (file_path, xml_file, "aplication/xml")}
        auth = (account.username, account.password)
        headers = {"Content-Type": "application/vnd.crossref.deposit+xml"}
        post_data(url, files=files, auth=auth, headers=headers)


@celery_app.task(bind=True)
def deposit_doi_in_crossref(self, prefix, username, user_id):
    url = "https://api.crossref.org/works/"
    try:
        data = CrossrefConfiguration.get_data(prefix=prefix)
    except CrossrefConfiguration.DoesNotExist:
        return None
    # TODO
    #COLOCAR FILTRO PARA NAO PROCESSAR NOVAMENTE
    xml_crossref = XMLCrossref.objects.filter(
        article__doi_with_lang__doi__icontains=data["prefix"]
    ).distinct()

    for xml in xml_crossref:
        for doi in xml.doi_with_lang.all():
            url_doi = re.sub(r"http\S//", "", doi.doi)
            url = url + url_doi
            try:
                verify_deposit_in_crossref(url)
                create_or_update_situation_crossref.apply_async(
                    kwargs=dict(xml=xml, record=True)
                )
            except (NonRetryableError, RetryableError) as e:
                try:
                    # Verifica se o XML ja foi enviado.
                    # Se nao, submete ele ao crossref
                    CrossrefDOIDepositRecord.get(xml_crossref=xml)
                except CrossrefDOIDepositRecord.DoesNotExist:
                    post_xml_in_crossref.apply_async(
                        kwargs=dict(xml_crossref=xml, username=username)
                    )
                    create_or_update_situation_crossref.apply_async(
                        kwargs=dict(xml=xml, record=False)
                    )
