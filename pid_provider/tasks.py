import logging

from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _

from config import celery_app
from libs.dsm.publication.documents import get_document
from libs.dsm.publication.db import mk_connection
from .controller import PidProvider


User = get_user_model()


@celery_app.task(bind=True, name=_("Request PID for documents registered in the new website"))
def request_pid_for_new_website_docs(
        self, pids_file_path, db_uri, user_id, files_storage_app_name):
    documents = _get_new_website_xmls(pids_file_path, db_uri)
    pid_provider = PidProvider(files_storage_app_name)
    for doc in documents:
        try:
            pid_provider.request_document_ids_for_xml_uri(
                doc['xml'], doc['v3'] + ".xml",
                User.objects.get(pk=user_id),
            )
        except Exception as e:
            logging.exception(
                f"Unable to get document which pid is {doc}"
            )


def _get_new_website_xmls(pids_file_path, db_uri):
    mk_connection(host=db_uri, alias=None)

    with open(pids_file_path) as fp:
        for pid in sorted(fp.readlines()):
            pid = pid.strip()
            try:
                document = get_document(pid=pid)
                if not document._id:
                    document = get_document(aop_pid=pid)
            except Exception as e:
                logging.exception(
                    f"Unable to get document which pid is {pid}"
                )
            else:
                yield {"xml": document.xml, "v3": document._id}
