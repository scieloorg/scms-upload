from opac_schema.v1.models import (
    Article,
    Journal,
    Issue,
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

    except KeyError as e:
        raise exceptions.DocumentDataError(e)

    try:
        doc.save()
    except Exception as e:
        raise exceptions.DocumentSaveError(e)

    return doc



