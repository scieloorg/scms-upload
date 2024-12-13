import logging
import json
from datetime import datetime

from django.utils.translation import gettext_lazy as _

from publication.api.publication import PublicationAPI
from publication.utils.document import build_article


def publish_article(article_proc, api_data, journal_pid=None, is_public=True):
    """
    {"failed": False, "id": article.id}
    {"failed": True, "error": str(ex)}
    """
    data = {}
    builder = ArticlePayload(data)

    try:
        # somente se article_proc é instancia de ArticleProc
        journal_pid = article_proc.issue_proc.journal_proc.pid
    except AttributeError:
        if not journal_pid:
            raise ValueError(
                "publication.api.document.publish_article requires journal_pid")

    order = article_proc.article.position
    pub_date = article_proc.article.first_publication_date or datetime.utcnow()

    build_article(builder, article_proc.article, journal_pid, order, pub_date, is_public)

    api = PublicationAPI(**api_data)
    kwargs = dict(
        article_id=data.get("_id"),
        issue_id=data.get("issue_id"),
        order=order,
        article_url=data.get("xml"),
    )
    return api.post_data(data, kwargs)


class ArticlePayload:
    # article_id, payload, issue_id, order, article_url
    # https://github.com/scieloorg/opac-airflow/blob/4103e6cab318b737dff66435650bc4aa0c794519/airflow/dags/operations/sync_kernel_to_website_operations.py#L82
    def __init__(self, data):
        self.data = data
        self.data["authors_meta"] = None
        self.data["authors"] = None
        self.data["translated_titles"] = None
        self.data["translated_sections"] = None
        self.data["abstract"] = None
        self.data["abstracts"] = None
        self.data["keywords"] = None
        self.data["doi_with_lang"] = None
        self.data["related_articles"] = None
        self.data["htmls"] = None
        self.data["pdfs"] = None
        self.data["mat_suppl_items"] = None

    def add_dates(self, created, updated):
        self.data["created"] = created.isoformat()
        if updated:
            self.data["updated"] = updated.isoformat()

    def add_issue(self, issue_id):
        self.data["issue_id"] = issue_id

    def add_identifiers(self, v3, v2, aop_pid, other_pids=None):
        # Identificadores
        self.data["_id"] = self.data.get("_id") or v3
        self.data["aid"] = self.data.get("aid") or v3
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
            self.data.setdefault("other_pids", [])
            if other_pid not in self.data["other_pids"]:
                self.data["other_pids"].append(other_pid)

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
        self.data["authors_meta"] = self.data["authors_meta"] or []
        author = {}
        author["surname"] = surname
        author["given_names"] = given_names
        author["suffix"] = suffix
        author["affiliation"] = affiliation
        author["orcid"] = orcid
        self.data["authors_meta"].append(author)

        # # author
        # if self.data["authors"] is None:
        #     self.data["authors"] = []
        # _author = format_author_name(
        #     surname,
        #     given_names,
        #     suffix,
        # )
        # self.data["authors"].append(_author)

    def add_collab(self, name):
        # collab
        self.data.setdefault("collabs", [])
        self.data["collabs"].append({"name": name})

    def add_translated_title(self, language, text):
        # translated_titles"] = EmbeddedDocumentListField(TranslatedTitle))
        if self.data["translated_titles"] is None:
            self.data["translated_titles"] = []
        _translated_title = {}
        _translated_title["name"] = text
        _translated_title["language"] = language
        self.data["translated_titles"].append(_translated_title)

    def add_section(self, language, text, code):
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

    def add_related_article(self, ref_id, related_type, ext_link_type, href):
        # related_article"] = EmbeddedDocumentListField(RelatedArticle))
        if self.data["related_articles"] is None:
            self.data["related_articles"] = []
        _related_article = {}
        if ext_link_type == "doi":
            _related_article["doi"] = href
            _related_article["ref_id"] = ref_id
            _related_article["related_type"] = related_type
            self.data["related_articles"].append(_related_article)
        else:
            pass
            # TODO depende de resolver https://github.com/scieloorg/opac_5/issues/212
            # _related_article["href"] = href
            # _related_article["ref_id"] = ref_id
            # _related_article["related_type"] = related_type
            # self.data["related_articles"].append(_related_article)
  
    def add_xml(self, xml):
        self.data["xml"] = xml

    def add_html(self, language, uri):
        # htmls"] = ListField(field=DictField()))
        if self.data["htmls"] is None:
            self.data["htmls"] = []
        self.data["htmls"].append({"lang": language, "uri": uri})
        # self.data["languages"] = [html["lang"] for html in self.data["htmls"]]

    def add_pdf(self, lang, url, filename, type, classic_uri=None):
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
                type="pdf",
                classic_uri=classic_uri,
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
        _mat_suppl_item["classic_uri"] = classic_uri
        self.data["mat_suppl_items"].append(_mat_suppl_item)

    def add_status(self, is_public=True):
        # atualiza status
        self.data["is_public"] = is_public


def format_author_name(surname, given_names, suffix):
    # like airflow
    if suffix:
        suffix = " " + suffix
    return "%s%s, %s" % (surname, suffix or "", given_names)
