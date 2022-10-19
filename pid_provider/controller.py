import os
import hashlib
import logging
from datetime import datetime
from http import HTTPStatus
from shutil import copyfile

from django.utils.translation import gettext as _

import requests

from libs.dsm.publication import documents as publication_documents

from upload.utils import package_utils
from collection import controller as collection_controller
from . import (
    models,
    exceptions,
    v3_gen,
    xml_sps_utils,
)


LOGGER = logging.getLogger(__name__)
LOGGER_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def get_registered_xml(xmltree):
    """
    Get registered XML

    Parameters
    ----------
    xmltree

    Returns
    -------
        models.XMLAOPArticle or models.XMLArticle

    Raises
    ------
    exceptions.FoundAOPPublishedInAnIssueError
    exceptions.GetRegisteredXMLError
    exceptions.RegisteredXMLDoesNotExistError
    """
    try:
        # obtém o registro do documento
        xml_adapter = xml_sps_utils.XMLAdapter(XML("", xmltree))
        registered = _get_registered_xml(xml_adapter)

        if registered and xml_adapter.is_aop and not registered.is_aop:
            # levanta exceção se está sendo ingressada uma versão aop de
            # artigo já publicado em fascículo
            raise exceptions.FoundAOPPublishedInAnIssueError(
                _("The XML content is an ahead of print version "
                  "but the document {} is already published in an issue"
                  ).format(registered)
            )
        if registered:
            return registered
        else:
            raise exceptions.RegisteredXMLDoesNotExistError(
                _("XML is not registered")
            )
    except Exception as e:
        raise exceptions.GetRegisteredXMLError(
            _("Unable to request document IDs for {}".format(xml_zip_file_path))
        )


def request_document_ids_for_zip(xml_zip_file_path, user_id):
    """
    Request PID v3

    Parameters
    ----------
    xml_zip_file_path : str
        XML URI
    user_id : str
        requester

    Returns
    -------
        dict which keys are v3 and xml_uri if applicable

    Raises
    ------
    exceptions.RequestDocumentIDsForXMLZipFileError
    """
    try:
        for item in xml_sps_utils.get_xml_items(xml_zip_file_path):
            try:
                # {"filename": item: "xml": xml}
                xml_adapter = xml_sps_utils.XMLAdapter(item['xml'])
                item['new_xml_uri'] = _request_document_ids(xml_adapter, user_id)
                yield item
            except Exception as e:
                raise exceptions.RequestDocumentIDsForXMLZipFileError(
                    _("Unable to request document IDs for {} {}".format(
                        xml_zip_file_path, item['filename'],
                        ))
                )
    except Exception as e:
        raise exceptions.RequestDocumentIDsForXMLZipFileError(
            _("Unable to request document IDs for {}".format(xml_zip_file_path))
        )


def request_document_ids_for_xml_uri(xml_uri, user_id):
    """
    Request PID v3

    Parameters
    ----------
    xml_uri : str
        XML URI
    user_id : str
        requester

    Returns
    -------
        dict which keys are v3 and xml_uri if applicable

    Raises
    ------
    exceptions.RequestDocumentIDsForXMLUriError

    """
    try:
        xml_adapter = _get_xml(xml_uri)
        return _request_document_ids(xml_adapter, user_id)
    except Exception as e:
        raise exceptions.RequestDocumentIDsForXMLUriError(
            _("Unable to request document IDs for XML URI {}".format(xml_uri))
        )


#############################################################################

def _get_content(uri, timeout=30):
    response = requests.get(uri, timeout=timeout)
    return response.content.decode("utf-8")


def _get_xml(xml_uri, timeout=30):
    LOGGER.debug("Get XML from {}".format(xml_uri))
    try:
        return xml_sps_utils.XMLAdapter(
            _get_content(xml_uri, timeout=timeout)
        )
    except Exception as e:
        logging.exception(e)
        raise exceptions.GetXMLFromURIError(
            _("Unable to get XML {} to request its PIDs: {} {}").format(
                xml_uri, type(e), e)
        )


def _put_xml(xml_content, object_name):
    LOGGER.debug("Put XML {}".format(object_name))
    try:
        files_storage = collection_controller.get_files_storage(
            collection_controller.get_files_storage_configuration(name='pid_provider')
        )

        return files_storage.fput_content(
            xml_content,
            mimetype="application/xml",
            object_name=object_name,
        )
    except Exception as e:
        logging.exception(e)
        raise exceptions.PutXMLError(
            _("Unable to put XML {}: {} {}").format(
                object_name, type(e), e)
        )


def _request_document_ids(xml_adapter, user_id):
    """
    Request PID v3

    Parameters
    ----------
    xml_adapter : XMLAdapter
        XMLAdapter
    user_id : str
        requester
    fput_content : callable
        store file by its content

    Returns
    -------
        dict which keys are v3 and xml_uri if applicable

    Raises
    ------
    exceptions.RequestDocumentIDsError
    exceptions.NotAllowedIngressingAOPVersionOfArticlePublishedInAnIssueError

    """
    try:
        response = {}
        # obtém o registro do documento
        registered = _get_registered_xml(xml_adapter)

        if registered and xml_adapter.is_aop and not registered.is_aop:
            # levanta exceção se está sendo ingressada uma versão aop de
            # artigo já publicado em fascículo
            raise exceptions.NotAllowedIngressingAOPVersionOfArticlePublishedInAnIssueError(
                _("Not allowed to ingress document {} as ahead of print, "
                  "because it is already published in an issue").format(registered)
            )

        # verfica os PIDs encontrados no XML / atualiza-os se necessário
        pids_updated = _check_xml_pids(xml_adapter, registered)

        xml_content = xml_adapter.tostring()
        xml_content_64_char = xml_sps_utils._str_with_64_char(xml_content)

        stored_xml = None
        if registered and registered.versions:
            # verifica se o xml já está registrado
            for stored_xml in registered.versions.filter(content=xml_content_64_char):
                break

        if not stored_xml:
            # registrar XML no files storage
            object_name = os.path.join(
                xml_adapter.v3,
                xml_content_64_char,
                xml_adapter.v3 + ".xml",
            )
            xml_uri = _put_xml(xml_content, object_name=object_name)

            xml_file = models.XMLFile(
                uri=xml_uri,
                created=datetime.utcnow(),
                content=xml_content_64_char,
            )
            xml_file.save()

            if registered:
                _update_registered_document(registered, xml_file, user_id)
            else:
                _register_new_document(xml_adapter, xml_file, user_id)
            response['xml_uri'] = xml_uri
        response['v3'] = xml_adapter.v3
    except Exception as e:
        raise exceptions.RequestDocumentIDsError(
            "Unable to request document IDs for {}".format(xml_adapter.v3)
        )

# DONE
def _get_registered_xml(xml_adapter):
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


def _get_query_params(kwargs):
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
            raise exceptions.NotEnoughParametersToGetDocumentRecordError(
                "No attribute to use for disambiguations"
            )
        _params["partial_body"] = xml_adapter.partial_body
    # journal
    if aop_version:
        _params['journal__issn_print'] = xml_adapter.journal_issn_print
        _params['journal__issn_electronic'] = xml_adapter.journal_issn_electronic
    else:
        _params['issue__journal__issn_print'] = xml_adapter.journal_issn_print
        _params['issue__journal__issn_electronic'] = xml_adapter.journal_issn_electronic

        if filter_by_issue:
            for k, v in xml_adapter.article_in_issue['issue'].items():
                _params[f"issue__{k}"] = v

    return _query_params(_params)


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


def _is_registered(v2=None, v3=None):
    if v3:
        kwargs = {"v3": v3}
    try:
        if v2:
            kwargs = {"v2": v2}
        return models.XMLArticle.objects.get(**kwargs)
    except models.XMLArticle.DoesNotExist:
        try:
            if aop_pid:
                kwargs = {"aop_pid": aop_pid}
            return models.XMLAOPArticle.objects.get(**kwargs)
        except models.XMLAOPArticle.DoesNotExist:
            return None

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
        if xml_adapter.is_aop and registered.is_aop:
            # XML é a versão AOP
            # registered é a versão AOP
            # garante que o valor de scielo-v2 é o mesmo valor de aop_pid
            xml_adapter.v2 = registered.aop_pid
        elif xml_adapter.is_aop:
            # XML é versão AOP
            # registered é a versão publicada em fascículo
            # levanta exceção porque XML é uma versão anterior a registrada
            raise exceptions.ForbiddenUpdatingAOPVersionOfArticlePublishedInAnIssueError(
                _("Not allowed to ingress document {} as ahead of print, "
                  "because it is already published in an issue").format(registered)
            )
        elif registered.is_aop:
            # XML é a versão publicada em fascículo
            # registered é a versão AOP, que não contém valor para atualizar v2
            pass

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
    yyyymmddtime = "".join([item for item in utcnow.isoformat() if item.isdigit()])
    mmdd = yyyymmddtime[4:8]
    nnnnn = str(utcnow.timestamp()).split(".")[0][-5:]
    return f"S{xml_adapter.v2_prefix}{mmdd}{nnnnn}"


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


def get_or_create_xml_journal(issn_electronic, issn_print):
    try:
        params = {
            "issn_electronic": issn_electronic,
            "issn_print": issn_print,
        }
        kwargs = _query_params(params)
        return models.XMLJournal.objects.get(**kwargs)
    except models.XMLJournal.DoesNotExist:
        journal = models.XMLJournal(**params)
        journal.save()
        return journal


def get_or_create_xml_issue(journal, volume, number, suppl, pub_year):
    try:
        params = {
            "volume": volume,
            "number": number,
            "suppl": suppl,
            "journal": journal,
            "pub_year": pub_year and int(pub_year) or None,
        }
        kwargs = _query_params(params)
        return models.XMLIssue.objects.get(**kwargs)
    except models.XMLIssue.DoesNotExist:
        issue = models.XMLIssue(**params)
        issue.save()
        return issue


def _update_registered_document(registered, xml_file, user_id):
    try:
        if registered:
            registered.versions.add(xml_file)
            registered.updated_by = user_id
            registered.updated = datetime.utcnow()
            registered.save()
            return
    except Exception as e:
        raise exceptions.SavingError(
            "Updating registered document error: %s %s %s" %
            (type(e), e, registered)
        )


def _register_new_document(xml_adapter, xml_file, user_id):
    try:
        if xml_adapter.is_aop:
            data = models.XMLAOPArticle()
            data.creator = user_id
            data.save()
            data.aop_pid = xml_adapter.v2
            data.journal = get_or_create_xml_journal(
                xml_adapter.journal_issn_electronic,
                xml_adapter.journal_issn_print,
            )
        else:
            data = models.XMLArticle()
            data.creator = user_id
            data.save()
            data.v2 = xml_adapter.v2
            journal = get_or_create_xml_journal(
                xml_adapter.journal_issn_electronic,
                xml_adapter.journal_issn_print,
            )
            data.issue = get_or_create_xml_issue(
                journal,
                xml_adapter.article_in_issue.get("volume"),
                xml_adapter.article_in_issue.get("number"),
                xml_adapter.article_in_issue.get("suppl"),
                xml_adapter.pub_year,
            )
            data.fpage = xml_adapter.article_in_issue.get("fpage")
            data.fpage_seq = xml_adapter.article_in_issue.get("fpage_seq")
            data.lpage = xml_adapter.article_in_issue.get("lpage")

        data.versions.add(xml_file)
        data.v3 = xml_adapter.v3
        data.main_doi = xml_adapter.main_doi
        data.elocation_id = xml_adapter.elocation_id
        data.article_titles_texts = xml_adapter.article_titles_texts
        data.surnames = xml_adapter.surnames
        data.collab = xml_adapter.collab
        data.links = xml_adapter.links
        data.partial_body = xml_adapter.partial_body

        data.creator = user_id

        data.save()

    except Exception as e:
        raise exceptions.SavingError(
            "Register new document error: %s %s %s" % (type(e), e, data)
        )


def sync_new_website_to_pid_provider_system(xmltree, user_id):
    """
    Busca documento em Pid Provider
    Se não o encontrar, tenta buscar no site novo e faz sincronização dos
    dados do site novo e do pid provider
    Retorna o item registrado em Pid Provider
    """
    try:
        try:
            # consulta pid provider
            return get_registered_xml(xmltree)
        except pid_provider_exceptions.RegisteredXMLDoesNotExistError:
            # tentar recuperar documento do site novo
            data = package_utils.get_article_data_for_comparison(xmltree)
            similar_docs = publication_documents.get_similar_documents(
                article_title=data["title"],
                journal_electronic_issn=data["journal_electronic_issn"],
                journal_print_issn=data["journal_print_issn"],
                authors=data["authors"],
            )

            for found_doc in similar_docs:
                try:
                    # obtém doc do site novo
                    doc = publication_documents.get_document(_id=found_doc.aid)

                    # registra dados do documento no pid provider system
                    registered = request_document_ids_for_xml_uri(
                        xml_uri=doc.xml, user_id=user_id,
                    )
                except Exception as e:
                    # TODO ???
                    pass
            # consulta novemente pid provider,
            # após inserção dos documentos similares em pid provider
            return get_registered_xml(xmltree)
    except Exception as e:
        # TODO ???
        raise exceptions.SyncNewWebsiteToPidProviderSystemError(
            _("Unable to sync new website to pid provider system {}").format(
                xmltree)
        )
