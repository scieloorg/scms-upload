import logging
from datetime import datetime

from django.utils.translation import gettext_lazy as _

from publication.utils.document import build_article
from publication.api.publication import PublicationAPI


def publish_article(user, website, scielo_article):
    try:
        data = {}
        builder = ArticlePayload(data)
        build_article(
            scielo_article.article, scielo_article.scielo_issue.scielo_journal, builder
        )

        api = PublicationAPI(
            post_data_url=website.api_url_article,
            get_token_url=website.api_get_token_url,
            username=website.api_username or user.username,
            password=website.api_password or user.password,
            timeout=website.api_timeout,
        )
        response = api.post_data(data)
        if response.get("result") == "OK":
            scielo_article.update_publication_stage()
            scielo_article.save()

    except Exception as e:
        logging.exception(e)
        # TODO registrar exceção no falhas de publicação


class ArticlePayload:
    # https://github.com/scieloorg/opac-airflow/blob/4103e6cab318b737dff66435650bc4aa0c794519/airflow/dags/operations/sync_kernel_to_website_operations.py#L82

    def __init__(self, data):
        self.data = data
        self.data["authors_meta"] = None
        self.data["authors"] = None
        self.data["translated_titles"] = None
        self.data["translated_sections"] = None
        self.data["abstracts"] = None
        self.data["keywords"] = None
        self.data["doi_with_lang"] = None
        self.data["related_articles"] = None
        self.data["htmls"] = None
        self.data["pdfs"] = None
        self.data["mat_suppl_items"] = None

    def add_journal(self, journal_id):
        self.data["journal"] = journal_id

    def add_issue(self, issue_id):
        self.data["issue"] = issue_id

    def add_identifiers(self, v3, v2, aop_pid, other_pids=None):
        # Identificadores
        self.data["_id"] = self.data["_id"] or v3
        self.data["aid"] = self.data["aid"] or v3
        self.data["pid"] = v2

        self.data["scielo_pids"] = {}
        self.data["scielo_pids_v2"] = v2
        self.data["scielo_pids_v3"] = v3

        if other_pids:
            for item in other_pids:
                self.add_other_pid(item)

        if aop_pid:
            self.data["aop_pid"] = aop_pid

    def add_other_pid(self, other_pid):
        if other_pid:
            self.data["scielo_pids"].setdefault("other", [])
            if other_pid not in self.data["scielo_pids"]["other"]:
                self.data["scielo_pids"]["other"].append(other_pid)

    def add_main_metadata(self, title, section, abstract, lang, doi):
        # Dados principais (versão considerada principal)
        # devem conter estilos html (math, italic, sup, sub)
        self.data["title"] = title
        self.data["section"] = section
        self.data["original_language"] = lang
        self.data["doi"] = doi

    def add_document_type(self, document_type):
        self.data["type"] = document_type

    def add_publication_date(self, year=None, month=None, day=None):
        if year and month and day:
            self.data["publication_date"] = "-".join([year, month, day])
        else:
            self.data["publication_date"] = datetime.now().isoformat()[:10]

    def add_in_issue(
        self, order, fpage=None, fpage_seq=None, lpage=None, elocation=None
    ):
        # Dados de localização no issue
        self.data["order"] = order
        self.data["elocation"] = elocation
        self.data["fpage"] = fpage
        self.data["fpage_sequence"] = fpage_seq
        self.data["lpage"] = lpage

    def add_author(self, surname, given_names, suffix, affiliation, orcid):
        # author meta
        # authors_meta"] = EmbeddedDocumentListField(AuthorMeta))
        if self.data["authors_meta"] is None:
            self.data["authors_meta"] = []
        author = {}
        author["surname"] = surname
        author["given_names"] = given_names
        author["suffix"] = suffix
        author["affiliation"] = affiliation
        author["orcid"] = orcid
        self.data["authors_meta"].append(author)

        # author
        if self.data["authors"] is None:
            self.data["authors"] = []
        _author = format_author_name(
            surname,
            given_names,
            suffix,
        )
        self.data["authors"].append(_author)

    def add_translated_title(self, language, text):
        # translated_titles"] = EmbeddedDocumentListField(TranslatedTitle))
        if self.data["translated_titles"] is None:
            self.data["translated_titles"] = []
        _translated_title = {}
        _translated_title["name"] = text
        _translated_title["language"] = language
        self.data["translated_titles"].append(_translated_title)

    def add_section(self, language, text):
        # sections"] = EmbeddedDocumentListField(TranslatedSection))
        if self.data["translated_sections"] is None:
            self.data["translated_sections"] = []
        _translated_section = {}
        _translated_section["name"] = text
        _translated_section["language"] = language
        self.data["translated_sections"].append(_translated_section)

    def add_abstract(self, language, text):
        # abstracts"] = EmbeddedDocumentListField(Abstract))
        if self.data["abstracts"] is None:
            self.data["abstracts"] = []
        if self.data["abstract"] is None:
            self.data["abstract"] = text
        _abstract = {}
        _abstract["text"] = text
        _abstract["language"] = language
        self.data["abstracts"].append(_abstract)

    def add_keywords(self, language, keywords):
        # kwd_groups"] = EmbeddedDocumentListField(ArticleKeyword))
        if self.data["keywords"] is None:
            self.data["keywords"] = []
        _kwd_group = {}
        _kwd_group["language"] = language
        _kwd_group["keywords"] = keywords
        self.data["keywords"].append(_kwd_group)

    def add_doi_with_lang(self, language, doi):
        # doi_with_lang"] = EmbeddedDocumentListField(DOIWithLang))
        if self.data["doi_with_lang"] is None:
            self.data["doi_with_lang"] = []
        _doi_with_lang_item = {}
        _doi_with_lang_item["doi"] = doi
        _doi_with_lang_item["language"] = language
        self.data["doi_with_lang"].append(_doi_with_lang_item)

    def add_related_article(self, doi, ref_id, related_type):
        # related_article"] = EmbeddedDocumentListField(RelatedArticle))
        if self.data["related_articles"] is None:
            self.data["related_articles"] = []
        _related_article = {}
        _related_article["doi"] = doi
        _related_article["ref_id"] = ref_id
        _related_article["related_type"] = related_type
        self.data["related_articles"].append(_related_article)

    def add_xml(self, xml):
        self.data["xml"] = xml

    def add_html(self, language, uri):
        # htmls"] = ListField(field=DictField()))
        if self.data["htmls"] is None:
            self.data["htmls"] = []
        self.data["htmls"].append({"lang": language, "uri": uri})
        self.data["languages"] = [html["lang"] for html in self.data["htmls"]]

    def add_pdf(self, lang, url, filename, type, classic_uri):
        # pdfs"] = ListField(field=DictField()))
        """
        {
            "lang": rendition["lang"],
            "url": rendition["url"],
            "filename": rendition["filename"],
            "type": "pdf",
        }
        """
        if self.data["pdfs"] is None:
            self.data["pdfs"] = []
        self.data["pdfs"].append(
            dict(
                lang=lang,
                url=url,
                filename=filename,
                type=type,
                # classic_uri=classic_uri,
            )
        )

    def add_mat_suppl(self, lang, url, ref_id, filename, classic_uri):
        # mat_suppl"] = EmbeddedDocumentListField(MatSuppl))
        if self.data["mat_suppl_items"] is None:
            self.data["mat_suppl_items"] = []
        _mat_suppl_item = {}
        _mat_suppl_item["url"] = url
        _mat_suppl_item["lang"] = lang
        _mat_suppl_item["ref_id"] = ref_id
        _mat_suppl_item["filename"] = filename
        # TODO
        # _mat_suppl_item.classic_uri"] = classic_uri
        self.data["mat_suppl_items"].append(_mat_suppl_item)

    def add_aop_url_segs(self):
        if self.data["issue"] and self.data["issue"]["number"] == "ahead":
            self.data["aop_url_segs"] = {
                "url_seg_article": self.data["url_segment"],
                "url_seg_issue": self.data["issue"]["url_segment"],
            }

    def add_status(self):
        # atualiza status
        if self.data["issue"]:
            self.data["issue"]["is_public"] = True
        self.data["is_public"] = True


def format_author_name(surname, given_names, suffix):
    # like airflow
    if suffix:
        suffix = " " + suffix
    return "%s%s, %s" % (surname, suffix or "", given_names)
