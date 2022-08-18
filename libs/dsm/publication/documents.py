from opac_schema.v1.models import (
    Abstract,
    AOPUrlSegments,
    Article,
    ArticleKeyword,
    AuthorMeta,
    DOIWithLang,
    Issue,
    Journal,
    MatSuppl,
    RelatedArticle,
    TranslatedSection,
    TranslatedTitle,
)

from . import exceptions
from .db import save_data


def get_document(doc_id):
    try:
        doc = Article.objects.get(_id=doc_id)
    except Article.DoesNotExist:
        doc = Article()
        doc._id = doc_id
        doc.aid = doc_id
    return doc


class Document:
    # https://github.com/scieloorg/opac-airflow/blob/4103e6cab318b737dff66435650bc4aa0c794519/airflow/dags/operations/sync_kernel_to_website_operations.py#L82

    def __init__(self, doc_id):
        self.doc = get_document(doc_id)

    def add_identifiers(self, v2, aop_pid, other_pids):
        # Identificadores
        self.doc.pid = v2

        self.doc.scielo_pids = {}
        self.doc.scielo_pids["v2"] = v2
        self.doc.scielo_pids["v3"] = self.doc._id

        if other_pids:
            self.doc.scielo_pids["other"] = other_pids

        if aop_pid:
            self.doc.aop_pid = aop_pid

    def add_other_pid(self, other_pid):
        if other_pid:
            self.doc.scielo_pids.setdefault("other", [])
            if other_pid not in self.doc.scielo_pids["other"]:
                self.doc.scielo_pids["other"].append(other_pid)

    def add_journal(self, journal):
        if isinstance(journal, Journal):
            self.doc.journal = journal
        else:
            self.doc.journal = Journal.objects.get(_id=journal)

    def add_issue(self, issue):
        if isinstance(issue, Issue):
            self.doc.issue = issue
        else:
            self.doc.issue = Issue.objects.get(_id=issue)

    def add_main_metadata(self, title, section, abstract, lang, doi):
        # Dados principais (versão considerada principal)
        # devem conter estilos html (math, italic, sup, sub)
        self.doc.title = title
        self.doc.section = section
        self.doc.abstract = abstract
        self.doc.original_language = lang
        self.doc.doi = doi

    def add_document_type(self, document_type):
        self.doc.type = document_type

    def add_publication_date(self, year, month, day):
        self.doc.publication_date = "-".join([year, month, day])

    def add_in_issue(self, order, fpage=None, fpage_seq=None, lpage=None, elocation=None):
        # Dados de localização no issue
        self.doc.order = order
        self.doc.elocation = elocation
        self.doc.fpage = fpage
        self.doc.fpage_sequence = fpage_seq
        self.doc.lpage = lpage

    def add_author(self, surname, given_names, suffix, affiliation, orcid):
        # author meta
        # authors_meta = EmbeddedDocumentListField(AuthorMeta))
        if self.doc.authors_meta is None:
            self.doc.authors_meta = []
        author = AuthorMeta()
        author.surname = surname
        author.given_names = given_names
        author.suffix = suffix
        author.affiliation = affiliation
        author.orcid = orcid
        self.doc.authors_meta.append(author)

        # author
        if self.doc.authors is None:
            self.doc.authors = []
        _author = format_author_name(
            surname, given_names, suffix,
        )
        self.doc.authors.append(_author)

    def add_translated_title(self, text, language):
        # translated_titles = EmbeddedDocumentListField(TranslatedTitle))
        if self.doc.translated_titles is None:
            self.doc.translated_titles = []
        _translated_title = TranslatedTitle()
        _translated_title.name = text
        _translated_title.language = language
        self.doc.translated_titles.append(_translated_title)

    def add_section(self, text, language):
        # sections = EmbeddedDocumentListField(TranslatedSection))
        if self.doc.translated_sections is None:
            self.doc.translated_sections = []
        _translated_section = TranslatedSection()
        _translated_section.name = text
        _translated_section.language = language
        self.doc.translated_sections.append(_translated_section)

    def add_abstract(self, text, language):
        # abstracts = EmbeddedDocumentListField(Abstract))
        if self.doc.abstracts is None:
            self.doc.abstracts = []
        _abstract = Abstract()
        _abstract.text = text
        _abstract.language = language
        self.doc.abstracts.append(_abstract)

    def add_keywords(self, lang, keywords):
        # kwd_groups = EmbeddedDocumentListField(ArticleKeyword))
        if self.doc.kwd_groups is None:
            self.doc.kwd_groups = []
        _kwd_group = ArticleKeyword()
        _kwd_group.lang = lang
        _kwd_group.keywords = keywords
        self.doc.kwd_groups.append(_kwd_group)

    def add_doi_with_lang(self, doi, language):
        # doi_with_lang = EmbeddedDocumentListField(DOIWithLang))
        if self.doc.doi_with_lang_items is None:
            self.doc.doi_with_lang_items = []
        _doi_with_lang_item = DOIWithLang()
        _doi_with_lang_item.doi = doi
        _doi_with_lang_item.language = language
        self.doc.doi_with_lang_items.append(_doi_with_lang_item)

    def add_related_article(self, doi, ref_id, related_type):
        # related_article = EmbeddedDocumentListField(RelatedArticle))
        if self.doc.related_articles is None:
            self.doc.related_articles = []
        _related_article = RelatedArticle()
        _related_article.doi = doi
        _related_article.ref_id = ref_id
        _related_article.related_type = related_type
        self.doc.related_articles.append(_related_article)

    def add_xml(self, xml):
        self.doc.xml = xml

    def add_html(self, language, uri):
        # htmls = ListField(field=DictField()))
        if self.doc.htmls is None:
            self.doc.htmls = []
        self.doc.htmls.append({"lang": language, "uri": uri})
        self.doc.languages = [html['lang'] for html in self.doc.htmls]

    def add_pdf(self, lang, url, filename, type):
        # pdfs = ListField(field=DictField()))
        """
        {
            "lang": rendition["lang"],
            "url": rendition["url"],
            "filename": rendition["filename"],
            "type": "pdf",
        }
        """
        if self.doc.pdfs is None:
            self.doc.pdfs = []
        self.doc.pdfs.append(
            dict(
                lang=lang,
                url=url,
                filename=filename,
                type=type,
            )
        )

    def add_mat_suppl(self, url, lang, ref_id, filename):
        # mat_suppl = EmbeddedDocumentListField(MatSuppl))
        if self.doc.mat_suppl_items is None:
            self.doc.mat_suppl_items = []
        _mat_suppl_item = MatSuppl()
        _mat_suppl_item.url = url
        _mat_suppl_item.lang = lang
        _mat_suppl_item.ref_id = ref_id
        _mat_suppl_item.filename = filename
        self.doc.mat_suppl_items.append(_mat_suppl_item)

    def publish_document(self):
        """
        Publishes doc data

        Raises
        ------
        DocumentSaveError

        Returns
        -------
        opac_schema.v1.models.Article
        """
        try:
            if self.doc.issue and self.doc.issue.number == "ahead":
                url_segs = {
                    "url_seg_article": self.doc.url_segment,
                    "url_seg_issue": self.doc.issue.url_segment,
                }
                self.doc.aop_url_segs = AOPUrlSegments(**url_segs)

            # atualiza status
            self.doc.issue.is_public = True
            self.doc.is_public = True
            save_data(self.doc)
        except Exception as e:
            raise exceptions.DocumentSaveError(e)
        return self.doc


def format_author_name(surname, given_names, suffix):
    # like airflow
    surname_and_suffix = surname
    if suffix:
        surname_and_suffix += " " + suffix
    return "%s%s, %s" % (surname_and_suffix, given_names)
