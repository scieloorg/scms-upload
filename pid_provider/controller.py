import os
import hashlib
import logging
from datetime import datetime
from http import HTTPStatus
from shutil import copyfile
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import requests
from requests.auth import HTTPBasicAuth
from django.utils.translation import gettext as _

from libs.dsm.publication import documents as publication_documents
from files_storage.controller import FilesStorageManager
from upload.utils import package_utils
from libs import xml_sps_utils as libs_xml_sps_utils
from . import (
    models,
    exceptions,
    v3_gen,
    xml_sps_utils,
)

LOGGER = logging.getLogger(__name__)
LOGGER_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class PidRequester:

    def __init__(self, files_storage_name, timeout=None):
        self.local_pid_provider = PidProvider(files_storage_name)
        self.api_uri = None
        self.timeout = timeout or 15

    def request_doc_ids(self, xml_with_pre, name, user):
        response = None
        if self.api_uri:
            response = self._api_request_doc_ids(xml_with_pre, name, user)

        if response:
            registered = self.local_pid_provider.request_document_ids_for_xml_uri(
                response["xml_uri"], name, user)
        else:
            registered = self.local_pid_provider.request_document_ids(
                xml_with_pre, name, user)

        if registered:
            return {
                "v3": registered.v3,
            }

    def _api_request_doc_ids(self, xml_with_pre, name, user):
        """
        name : str
            nome do arquivo xml
        """

        with TemporaryDirectory() as tmpdirname:
            zip_xml_file_path = os.path.join(tmpdirname, name + ".zip")

            xml_filename = name
            name, ext = os.path.splitext(xml_filename)

            with ZipFile(zip_xml_file_path, "w") as zf:
                zf.writestr(xml_filename, xml_with_pre.tostring())

            with open(zip_xml_file_path, "rb") as fp:
                # {"v3": v3, "xml_uri": xml_uri}
                return self._api_request_post(
                    fp, xml_filename, user, self.timeout)

    def _api_request_post(self, fp, xml_filename, user, timeout):
        # TODO retry
        try:
            auth = HTTPBasicAuth(user.name, user.password)
            return requests.post(
                self.api_uri,
                files={"zip_xml_file_path": fp},
                auth=auth,
                timeout=timeout,
            )
        except Exception as e:
            # TODO tratar as exceções
            logging.exception(e)


class PidProvider:

    def __init__(self, files_storage_name):
        self.files_storage_manager = FilesStorageManager(files_storage_name)

    def request_document_ids(self, xml_with_pre, filename, user):
        """
        Request PID v3

        Parameters
        ----------
        xml : XMLWithPre
        filename : str

        Returns
        -------
            None or models.XMLAOPArticle or models.XMLArticle

        Raises
        ------
        exceptions.RequestDocumentIDsError
        exceptions.NotAllowedIngressingAOPVersionOfArticlePublishedInAnIssueError

        """
        try:
            # obtém o registro do documento
            logging.info("request_document_ids for {}".format(filename))

            # adaptador do xml with pre
            xml_adapter = xml_sps_utils.XMLAdapter(xml_with_pre)

            logging.info("_get_registered_xml")
            registered = _get_registered_xml(xml_adapter)
            logging.info("REGISTERED? %s" % registered)

            # verfica os PIDs encontrados no XML / atualiza-os se necessário
            pids_updated = _check_xml_pids(xml_adapter, registered)

            if not registered:
                # cria registro
                registered = _register_new_document(xml_adapter, user)
                logging.info("new %s" % registered)

            if registered:
                self.files_storage_manager.register_pid_provider_xml(
                    registered.versions,
                    filename,
                    xml_adapter.tostring(),
                    user,
                )
                return registered

        except exceptions.FoundAOPPublishedInAnIssueError:
            logging.exception(e)
            raise exceptions.NotAllowedIngressingAOPVersionOfArticlePublishedInAnIssueError(
                _("Not allowed to ingress document {} as ahead of print, "
                  "because it is already published in an issue").format(registered)
            )

        except Exception as e:
            logging.exception(e)
            raise exceptions.RequestDocumentIDsError(
                f"Unable to request document IDs for {xml_with_pre} {type(e)} {str(e)}"
            )

    def request_document_ids_for_xml_zip(self, zip_xml_file_path, user):
        """
        Request PID v3

        Parameters
        ----------
        zip_xml_file_path : str
            XML URI

        Returns
        -------
            models.XMLAOPArticle or models.XMLArticle

        Raises
        ------
        exceptions.RequestDocumentIDsForXMLZipFileError
        """
        try:
            for item in libs_xml_sps_utils.get_xml_items(zip_xml_file_path):
                try:
                    # {"filename": item: "xml": xml}
                    registered = self.request_document_ids(
                        item['xml_with_pre'], item["filename"], user)
                    if registered:
                        item.update({"registered": registered})
                    yield item
                except Exception as e:
                    logging.exception(e)
                    raise exceptions.RequestDocumentIDsForXMLZipFileError(
                        _("Unable to request document IDs for {} {}".format(
                            zip_xml_file_path, item['filename'],
                            ))
                    )
        except Exception as e:
            logging.exception(e)
            raise exceptions.RequestDocumentIDsForXMLZipFileError(
                _("Unable to request document IDs for {}").format(
                    zip_xml_file_path)
            )

    def request_document_ids_for_xml_uri(self, xml_uri, filename, user):
        try:
            result = models.RequestResult.create(xml_uri, user)
            xml_with_pre = libs_xml_sps_utils.get_xml_with_pre_from_uri(xml_uri)
            registered = self.request_document_ids(xml_with_pre, filename, user)
            result.update(user, v3=registered.v3)
            return registered
        except Exception as e:
            result.update(user, error_msg=str(e), error_type=type(e))

    def is_registered(self, xml_with_pre):
        """
        Check if article is registered

        Parameters
        ----------
        xml : XMLWithPre

        Returns
        -------
            None or models.XMLAOPArticle or models.XMLArticle

        Raises
        ------
        exceptions.RequestDocumentIDsError
        exceptions.FoundAOPPublishedInAnIssueError

        """
        try:
            # adaptador do xml with pre
            xml_adapter = xml_sps_utils.XMLAdapter(xml_with_pre)
            return _query_document(xml_adapter)

        except Exception as e:
            logging.exception(e)
            raise exceptions.IsRegisteredError(
                _("Unable to request document IDs for {}").format(
                    zip_xml_file_path)
            )

    def is_registered_xml_zip(self, zip_xml_file_path):
        """
        Check if article is registered

        Parameters
        ----------
        zip_xml_file_path : str
            XML URI

        Returns
        -------
            models.XMLAOPArticle or models.XMLArticle

        Raises
        ------
        exceptions.IsRegisteredXMLZipError
        """
        try:
            for item in libs_xml_sps_utils.get_xml_items(zip_xml_file_path):
                try:
                    # {"filename": item: "xml": xml}
                    registered = self.is_registered(item['xml_with_pre'])
                    if registered:
                        item.update({"registered": registered})
                    yield item
                except Exception as e:
                    logging.exception(e)
                    raise exceptions.IsRegisteredXMLZipError(
                        _("Unable to request document IDs for {} {}".format(
                            zip_xml_file_path, item['filename'],
                            ))
                    )
        except Exception as e:
            logging.exception(e)
            raise exceptions.IsRegisteredXMLZipError(
                _("Unable to request document IDs for {}").format(
                    zip_xml_file_path)
            )

    def is_registered_xml_uri(self, xml_uri):
        try:
            xml_with_pre = libs_xml_sps_utils.get_xml_with_pre_from_uri(xml_uri)
            return self.is_registered(xml_with_pre)
        except Exception as e:
            logging.exception(e)
            raise exceptions.IsRegisteredForXMLUriError(e)


def _get_registered_xml(xml_adapter):
    """
    Get registered XML

    Parameters
    ----------
    xml_adapter : XMLAdapter

    Returns
    -------
        None or models.XMLAOPArticle or models.XMLArticle

    Raises
    ------
    exceptions.FoundAOPPublishedInAnIssueError
    exceptions.GetRegisteredXMLError
    """
    try:
        # obtém o registro do documento
        logging.info(xml_adapter)
        registered = _query_document(xml_adapter)

        if registered and xml_adapter.is_aop and not registered.is_aop:
            # levanta exceção se está sendo ingressada uma versão aop de
            # artigo já publicado em fascículo
            logging.exception(e)
            raise exceptions.FoundAOPPublishedInAnIssueError(
                _("The XML content is an ahead of print version "
                  "but the document {} is already published in an issue"
                  ).format(registered)
            )
        return registered
    except Exception as e:
        logging.exception(e)
        raise exceptions.GetRegisteredXMLError(
            _(f"Unable to get registered XML {xml_adapter} {type(e)} {str(e)}")
        )


# DONE
def _query_document(xml_adapter):
    """
    Get registered document

    Arguments
    ---------
    xml_adapter : XMLAdapter

    Returns
    -------
    None or models.XMLArticle or models.XMLAOPArticle

    # Raises
    # ------
    # models.XMLArticle.MultipleObjectsReturned
    # models.XMLAOPArticle.MultipleObjectsReturned
    """
    logging.info("xml_adapter.is_aop: %s" % xml_adapter.is_aop)
    if xml_adapter.is_aop:
        # o documento de entrada é um AOP
        try:
            # busca este documento na versão publicada em fascículo,
            # SEM dados de fascículo
            params = _query_document_args(xml_adapter, aop_version=False)
            return models.XMLArticle.objects.get(**params)
        except models.XMLArticle.DoesNotExist:
            try:
                # busca este documento na versão publicada como AOP
                params = _query_document_args(xml_adapter, aop_version=True)
                return models.XMLAOPArticle.objects.get(**params)
            except models.XMLAOPArticle.DoesNotExist:
                return None
        except Exception as e:
            logging.exception(e)

    else:
        # o documento de entrada contém dados de issue
        try:
            # busca este documento na versão publicada em fascículo,
            # COM dados de fascículo
            params = _query_document_args(xml_adapter, filter_by_issue=True)
            return models.XMLArticle.objects.get(**params)
        except models.XMLArticle.DoesNotExist:
            try:
                # busca este documento na versão publicada como AOP,
                # SEM dados de fascículo,
                # pois este pode ser uma atualização da versão AOP
                params = _query_document_args(xml_adapter, aop_version=True)
                return models.XMLAOPArticle.objects.get(**params)
            except models.XMLAOPArticle.DoesNotExist:
                return None
        except Exception as e:
            logging.exception(e)


def _set_isnull_parameters(kwargs):
    _kwargs = {}
    for k, v in kwargs.items():
        if v:
            _kwargs[k] = v
        else:
            _kwargs[f"{k}__isnull"] = True
    return _kwargs


def _query_document_args(xml_adapter, filter_by_issue=False, aop_version=False):
    """
    Get query parameters

    Arguments
    ---------
    xml_adapter : XMLAdapter
    aop_version: bool
    filter_by_issue: bool

    Returns
    -------
    dict
    """
    _params = dict(
        surnames=xml_adapter.surnames or None,
        article_titles_texts=xml_adapter.article_titles_texts or None,
        collab=xml_adapter.collab or None,
        links=xml_adapter.links or None,
        main_doi=xml_adapter.main_doi or None,
    )
    if not any(_params.values()):
        # nenhum destes, então procurar pelo início do body
        if not xml_adapter.partial_body:
            logging.exception(e)
            raise exceptions.NotEnoughParametersToGetDocumentRecordError(
                "No attribute to use for disambiguations"
            )
        _params["partial_body"] = xml_adapter.partial_body
    if aop_version:
        _params['journal__issn_print'] = xml_adapter.journal_issn_print
        _params['journal__issn_electronic'] = xml_adapter.journal_issn_electronic
    else:
        _params['issue__journal__issn_print'] = xml_adapter.journal_issn_print
        _params['issue__journal__issn_electronic'] = xml_adapter.journal_issn_electronic

        if filter_by_issue:
            for k, v in xml_adapter.issue.items():
                _params[f"issue__{k}"] = v
            _params.update(xml_adapter.pages)

    params = _set_isnull_parameters(_params)
    logging.info(dict(filter_by_issue=filter_by_issue, aop_version=aop_version))
    logging.info(params)
    return params


###############################################################################
# TODO
def _check_xml_pids(xml_adapter, registered):
    """
    Update `xml_adapter` pids with `registered` pids or
    create `xml_adapter` pids

    Parameters
    ----------
    xml_adapter: XMLAdapter
    registered: models.XMLArticle or models.XMLAOPArticle

    Returns
    -------
    bool

    """
    xml_ids = (xml_adapter.v2, xml_adapter.v3, xml_adapter.aop_pid)

    # adiciona os pids faltantes aos dados de entrada
    _add_pid_v3(xml_adapter, registered)
    _add_pid_v2(xml_adapter, registered)
    _add_aop_pid(xml_adapter, registered)

    # print(ids, new_ids)
    logging.info(
        "%s %s" %
        (xml_ids, (xml_adapter.v2, xml_adapter.v3, xml_adapter.aop_pid))
    )
    return xml_ids != (xml_adapter.v2, xml_adapter.v3, xml_adapter.aop_pid)


###############################################################################
def _add_pid_v3(xml_adapter, registered):
    """
    Garante que xml_adapter tenha um v3 inédito

    Arguments
    ---------
    xml_adapter: XMLAdapter
    registered: models.XMLArticle or models.XMLAOPArticle or None

    """
    if registered:
        xml_adapter.v3 = registered.v3
    else:
        if not xml_adapter.v3 or _is_registered(v3=xml_adapter.v3):
            xml_adapter.v3 = _get_unique_v3()


def _get_unique_v3():
    """
    Generate v3 and return it only if it is new

    Returns
    -------
        str
    """
    while True:
        generated = v3_gen.generates()
        if not _is_registered(generated):
            return generated


def _is_registered(v2=None, v3=None, aop_pid=None):
    params = dict(v2=v2, v3=v3, aop_pid=aop_pid)
    kwargs = {k: v for k, v in params.items() if v}

    if kwargs.get("v3"):
        try:
            found = models.XMLArticle.objects.filter(**kwargs)[0]
        except IndexError:
            try:
                found = models.XMLAOPArticle.objects.filter(**kwargs)[0]
            except IndexError:
                return False
            else:
                return True
        else:
            return True
    if kwargs.get("v2"):
        try:
            found = models.XMLArticle.objects.filter(**kwargs)[0]
        except IndexError:
            return False
        else:
            return True
    if kwargs.get("aop_pid"):
        try:
            found = models.XMLAOPArticle.objects.filter(**kwargs)[0]
        except IndexError:
            return False
        else:
            return True

##############################################


def _add_pid_v2(xml_adapter, registered):
    """
    Garante que xml_adapter tenha um v2 inédito

    Arguments
    ---------
    xml_adapter: XMLAdapter
    registered: models.XMLArticle or models.XMLAOPArticle or None

    Returns
    -------
        dict
    """
    if registered:
        if not xml_adapter.is_aop and not registered.is_aop:
            # versão VoR: xml e registered
            xml_adapter.v2 = registered.v2
            return

        if xml_adapter.is_aop and registered.is_aop:
            # versão AOP: xml e registered
            # garante que o valor de scielo-v2 é o mesmo valor de aop_pid
            xml_adapter.v2 = registered.aop_pid
            return

        if xml_adapter.is_aop:
            # versão AOP: xml
            # versão VoR: registered
            # levanta exceção porque XML é uma versão anterior a registrada
            logging.exception(e)
            raise exceptions.ForbiddenUpdatingAOPVersionOfArticlePublishedInAnIssueError(
                _("Not allowed to ingress document {} as ahead of print, "
                  "because it is already published in an issue").format(registered)
            )
    if not registered or registered.is_aop:
        # não existe registered.v2
        # então manter xml_adapter.v2 ou gerar v2 para xml_adapter
        if not xml_adapter.v2 or _is_registered(v2=xml_adapter.v2):
            # gera v2 para manter compatibilidade com o legado
            xml_adapter.v2 = _get_unique_v2(xml_adapter)


def _get_unique_v2(xml_adapter):
    """
    Generate v2 and return it only if it is new

    Returns
    -------
        str
    """
    while True:
        generated = _v2_generates(xml_adapter)
        if not _is_registered(v2=generated):
            return generated


def _v2_generates(xml_adapter):
    # '2022-10-19T13:51:33.830085'
    utcnow = datetime.utcnow()
    yyyymmddtime = "".join(
        [item for item in utcnow.isoformat() if item.isdigit()])
    mmdd = yyyymmddtime[4:8]
    nnnnn = str(utcnow.timestamp()).split(".")[0][-5:]
    return f"{xml_adapter.v2_prefix}{mmdd}{nnnnn}"


###############################################################################


def _add_aop_pid(xml_adapter, registered):
    """
    Atualiza xml_adapter com aop_pid se aplicável

    Arguments
    ---------
    xml_adapter: XMLAdapter
    registered: models.XMLArticle or models.XMLAOPArticle or None

    Returns
    -------
        dict
    """
    if registered:
        if registered.is_aop:
            xml_adapter.aop_pid = registered.aop_pid
        elif xml_adapter.is_aop:
            try:
                xml_aop_article = models.XMLAOPArticle.objects.get(aop_pid=registered.aop_pid)
            except models.XMLAOPArticle.DoesNotExist:
                pass
            else:
                xml_adapter.aop_pid = xml_aop_article.aop_pid


###############################################################################


def _get_or_create_xml_journal(issn_electronic, issn_print):
    try:
        params = {
            "issn_electronic": issn_electronic,
            "issn_print": issn_print,
        }
        kwargs = _set_isnull_parameters(params)
        logging.info("Search {}".format(kwargs))
        return models.XMLJournal.objects.get(**kwargs)
    except models.XMLJournal.DoesNotExist:
        params = {k: v for k, v in params.items() if v}
        logging.info("Create {}".format(params))
        journal = models.XMLJournal(**params)
        journal.save()
        return journal


def _get_or_create_xml_issue(journal, volume, number, suppl, pub_year):
    try:
        params = {
            "volume": volume,
            "number": number,
            "suppl": suppl,
            "journal": journal,
            "pub_year": pub_year and int(pub_year) or None,
        }
        kwargs = _set_isnull_parameters(params)
        logging.info("Search {}".format(kwargs))
        return models.XMLIssue.objects.get(**kwargs)
    except models.XMLIssue.DoesNotExist:
        params = {k: v for k, v in params.items() if v}
        logging.info("Create {}".format(params))
        issue = models.XMLIssue(**params)
        issue.save()
        return issue


def _register_new_document(xml_adapter, user):
    try:
        if xml_adapter.is_aop:
            data = models.XMLAOPArticle()
            data.creator = user
            data.save()
            data.aop_pid = xml_adapter.v2
            data.journal = _get_or_create_xml_journal(
                xml_adapter.journal_issn_electronic,
                xml_adapter.journal_issn_print,
            )
        else:
            data = models.XMLArticle()
            data.creator = user
            data.save()
            data.v2 = xml_adapter.v2
            journal = _get_or_create_xml_journal(
                xml_adapter.journal_issn_electronic,
                xml_adapter.journal_issn_print,
            )
            data.issue = _get_or_create_xml_issue(
                journal,
                xml_adapter.issue.get("volume"),
                xml_adapter.issue.get("number"),
                xml_adapter.issue.get("suppl"),
                xml_adapter.issue.get("pub_year"),
            )
            data.fpage = xml_adapter.pages.get("fpage")
            data.fpage_seq = xml_adapter.pages.get("fpage_seq")
            data.lpage = xml_adapter.pages.get("lpage")
            data.elocation_id = xml_adapter.pages.get("elocation_id")

        data.v3 = xml_adapter.v3
        data.main_doi = xml_adapter.main_doi
        data.article_titles_texts = xml_adapter.article_titles_texts
        data.surnames = xml_adapter.surnames
        data.collab = xml_adapter.collab
        data.links = xml_adapter.links
        data.partial_body = xml_adapter.partial_body
        data.save()
        return data

    except Exception as e:
        logging.info(f"{data.v3} {str(data.v3)}")
        if hasattr(data, 'v2'):
            logging.info(f"{data.v2} {str(data.v2)}")
        if hasattr(data, 'aop_pid'):
            logging.info(f"{data.aop_pid} {str(data.aop_pid)}")

        logging.exception(e)
        raise exceptions.SavingError(
            "Register new document error: %s %s %s" % (type(e), e, data)
        )
