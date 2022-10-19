import os
import hashlib
import logging
from datetime import datetime
from http import HTTPStatus
from shutil import copyfile

import requests

from django.utils.translation import gettext as _
from django.contrib.auth import get_user_model

from libs.dsm.publication import documents as publication_documents

from upload.utils import package_utils
from libs import xml_sps_utils as libs_xml_sps_utils
from . import (
    models,
    exceptions,
    v3_gen,
    xml_sps_utils,
)

User = get_user_model()

LOGGER = logging.getLogger(__name__)
LOGGER_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def get_registered_xml(xml, user_id, fput_content):
    """
    Get registered XML

    Parameters
    ----------
    xml : XMLPre

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
        xml_adapter = xml_sps_utils.XMLAdapter(xml)
        logging.info("ADAPT")
        logging.info(xml_adapter)
        registered = _query_document(xml_adapter)
        if not registered:
            _sync_new_website_to_pid_provider_system(
                xml_adapter.xmltree, user_id, fput_content)
            registered = _query_document(xml_adapter)

        if registered and xml_adapter.is_aop and not registered.is_aop:
            # levanta exceção se está sendo ingressada uma versão aop de
            # artigo já publicado em fascículo
            raise exceptions.FoundAOPPublishedInAnIssueError(
                _("The XML content is an ahead of print version "
                  "but the document {} is already published in an issue"
                  ).format(registered)
            )
        return registered
    except Exception as e:
        raise exceptions.GetRegisteredXMLError(
            _("Unable to get registered XML {}").format(xml)
        )


def request_document_ids_for_zip(xml_zip_file_path, user_id, fput_content):
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
        models.XMLAOPArticle or models.XMLArticle

    Raises
    ------
    exceptions.RequestDocumentIDsForXMLZipFileError
    """
    try:
        for item in libs_xml_sps_utils.get_xml_items(xml_zip_file_path):
            try:
                # {"filename": item: "xml": xml}
                registered = request_document_ids(
                    item['xml'], user_id, fput_content, item["filename"])
                if registered:
                    item.update({"registered": registered})
                yield item
            except Exception as e:
                raise exceptions.RequestDocumentIDsForXMLZipFileError(
                    _("Unable to request document IDs for {} {}".format(
                        xml_zip_file_path, item['filename'],
                        ))
                )
    except Exception as e:
        raise exceptions.RequestDocumentIDsForXMLZipFileError(
            _("Unable to request document IDs for {}").format(
                xml_zip_file_path)
        )


def request_document_ids(xml, user_id, fput_content, object_name):
    """
    Request PID v3

    Parameters
    ----------
    xml : XMLPre
    user_id : str
        requester

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
        logging.info("Inicio request_document_ids {}".format(object_name))
        registered = get_registered_xml(xml, user_id, fput_content)

        xml_adapter = xml_sps_utils.XMLAdapter(xml)

        # verfica os PIDs encontrados no XML / atualiza-os se necessário
        pids_updated = _check_xml_pids(xml_adapter, registered)

        if not registered:
            # cria registro
            registered = _register_new_document(xml_adapter, user_id)

        if registered:
            xml_content = xml.tostring()
            xml_uri = fput_content(
                xml_content,
                mimetype="text/xml",
                object_name=object_name
            )
            _update_xml_versions(registered, user_id, xml_uri, xml_content)

        return registered

    except exceptions.FoundAOPPublishedInAnIssueError:
        raise exceptions.NotAllowedIngressingAOPVersionOfArticlePublishedInAnIssueError(
            _("Not allowed to ingress document {} as ahead of print, "
              "because it is already published in an issue").format(registered)
        )

    except Exception as e:
        raise exceptions.RequestDocumentIDsError(
            "Unable to request document IDs for {}".format(xml)
        )


def _update_xml_versions(registered, user_id, xml_uri, xml_content):
    """
    Adiciona xml_uri no registro de pid_provider

    Parameters
    ----------
    registered : models.XMLAOPArticle or models.XMLArticle
    user_id : str
        requester
    xml_uri : str

    Returns
    -------
        None or models.XMLAOPArticle or models.XMLArticle

    Raises
    ------
    exceptions.SaveXMLFileError

    """
    try:
        # verifica se o xml já está registrado
        exist = False
        xml_content_64_char = xml_sps_utils._str_with_64_char(xml_content)
        try:
            current = registered.versions.latest('created')
        except models.XMLFile.DoesNotExist:
            pass
        else:
            exist = (current.content == xml_content_64_char)
        if not exist:
            xml_file = models.XMLFile(
                uri=xml_uri,
                created=datetime.utcnow(),
                content=xml_content_64_char,
            )
            xml_file.save()

            return _add_xml_file(registered, xml_file, user_id)

    except Exception as e:
        raise exceptions.SaveXMLFileError(
            "Unable to save xml file {} in pid provider".format(xml_uri)
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


def _add_xml_file(registered, xml_file, user_id):
    try:
        if registered:
            registered.versions.add(xml_file)
            registered.updated_by = User.objects.get(pk=user_id)
            registered.updated = datetime.utcnow()
            registered.save()
            return registered
    except Exception as e:
        raise exceptions.SavingError(
            "Add XML file to registered document error: %s %s %s" %
            (type(e), e, registered)
        )


def _register_new_document(xml_adapter, user_id):
    try:
        if xml_adapter.is_aop:
            data = models.XMLAOPArticle()
            data.creator = User.objects.get(pk=user_id)
            data.save()
            data.aop_pid = xml_adapter.v2
            data.journal = _get_or_create_xml_journal(
                xml_adapter.journal_issn_electronic,
                xml_adapter.journal_issn_print,
            )
        else:
            data = models.XMLArticle()
            data.creator = User.objects.get(pk=user_id)
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
        logging.info(f"{data.v3} {len(data.v3)}")
        if hasattr(data, 'v2'):
            logging.info(f"{data.v2} {len(data.v2)}")
        if hasattr(data, 'aop_pid'):
            logging.info(f"{data.aop_pid} {len(data.aop_pid)}")

        raise exceptions.SavingError(
            "Register new document error: %s %s %s" % (type(e), e, data)
        )


def _sync_new_website_to_pid_provider_system(xmltree, user_id, fput_content):
    """
    Faz sincronização dos dados do site novo e do pid provider
    Retorna o item registrado em Pid Provider
    """
    try:
        # tentar recuperar documento do site novo
        data = package_utils.get_article_data_for_comparison(xmltree)
        new_website_docs = publication_documents.get_similar_documents(
            article_title=data["title"],
            journal_electronic_issn=data["journal_electronic_issn"],
            journal_print_issn=data["journal_print_issn"],
            authors=data["authors"],
        )

        for found_doc in new_website_docs:
            try:
                # registra dados do documento no pid provider system
                xml = libs_xml_sps_utils.get__xml__from_uri(
                    found_doc.xml)
                registered = request_document_ids(
                    xml, user_id, fput_content, found_doc._id)
            except Exception as e:
                # TODO ???
                raise exceptions.SyncNewWebsiteToPidProviderSystemError(
                    _("Unable to register {} in pid provider system").format(
                        found_doc.xml)
                )
    except Exception as e:
        # TODO ???
        raise exceptions.SyncNewWebsiteToPidProviderSystemError(
            _("Unable to sync new website to pid provider system {}").format(
                xmltree)
        )
