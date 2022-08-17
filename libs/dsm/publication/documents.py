from opac_schema.v1.models import (
    Article,
    Journal,
    Issue,
    AuthorMeta,
)

from . import exceptions



def get_document(doc_id):
    try:
        doc = Article.objects.get(_id=doc_id)
    except Article.DoesNotExist:
        doc = Article()
        doc._id = doc_id
    return doc


def publish_document(doc_data):
    """
    Publishes doc data
    # https://github.com/scieloorg/opac-airflow/blob/4103e6cab318b737dff66435650bc4aa0c794519/airflow/dags/operations/sync_kernel_to_website_operations.py#L82

    Parameters
    ----------
    doc_data : dict

    Raises
    ------
    DocumentDataError
    DocumentSaveError

    Returns
    -------
    Document
    """
    try:
        doc = get_document(doc_data["id"])
        doc.journal = Journal.objects.get(_id=doc_data["journal_id"])
        doc.issue = Issue.objects.get(_id=doc_data["issue_id"])
        doc.issue.is_public = True

        # atualiza status
        doc.is_public = True

        # Dados principais (versão considerada principal)
        # devem conter estilos html (math, italic, sup, sub)
        doc.title = doc_data["title"]
        doc.section = doc_data["section"]
        doc.abstract = doc_data["abstract"]
        doc.original_language = doc_data["language"]
        doc.doi = doc_data.get("doi")

        # Identificadores
        doc._id = doc_data["id"]
        doc.aid = doc_data["id"]
        doc.pid = doc_data["v2"]

        doc.scielo_pids = {}
        doc.scielo_pids["v2"] = doc_data["v2"]
        doc.scielo_pids["v3"] = doc_data["v3"]

        if doc_data.get("other"):
            doc.scielo_pids["other"] = doc_data.get("other_pids")

        if doc_data.get("aop_pid"):
            doc.aop_pid = doc_data.get("aop_pid")

        doc.publication_date = doc_data["publication_date"]
        doc.type = doc_data["publication_type"]

        # Dados de localização no issue
        doc.elocation = doc_data["elocation"]
        doc.fpage = doc_data["fpage"]
        doc.fpage_sequence = doc_data["fpage_seq"]
        doc.lpage = doc_data["lpage"]

        doc.order = doc_data["order"]

        doc.xml = doc_data["xml"]

        for item in doc_data.get("authors"):
            add_author(
                doc,
                item["surname"],
                item["given_names"],
                item.get("suffix"),
            )
            add_author_meta(
                doc,
                item["surname"],
                item["given_names"],
                item.get("suffix"),
                item.get("affiliation"),
                item.get("orcid"),
            )

    except KeyError as e:
        raise exceptions.DocumentDataError(e)

    try:
        doc.save()
    except Exception as e:
        raise exceptions.DocumentSaveError(e)

    return doc


def add_author(document, surname, given_names, suffix):
    # authors = EmbeddedDocumentListField(Author))
    if document.authors is None:
        document.authors = []
    _author = format_author_name(
        surname, given_names, suffix,
    )
    document.authors.append(_author)


def format_author_name(surname, given_names, suffix):
    # like airflow
    surname_and_suffix = surname
    if suffix:
        surname_and_suffix += " " + suffix
    return "%s%s, %s" % (surname_and_suffix, given_names)


def add_author_meta(document, surname, given_names, suffix, affiliation, orcid):
    # authors_meta = EmbeddedDocumentListField(AuthorMeta))
    if document.authors_meta is None:
        document.authors_meta = []
    author = AuthorMeta()
    author.surname = surname
    author.given_names = given_names
    author.suffix = suffix
    author.affiliation = affiliation
    author.orcid = orcid
    document.authors_meta.append(author)

