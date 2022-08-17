from opac_schema.v1 import models

from . import exceptions

# https://github.com/scieloorg/opac-airflow/blob/4103e6cab318b737dff66435650bc4aa0c794519/airflow/dags/operations/sync_kernel_to_website_operations.py#L82


def get_document(doc_id):
    try:
        doc = models.Article.objects.get(_id=doc_id)
    except models.Article.DoesNotExist:
        doc = models.Article()
        doc._id = doc_id
    return doc

