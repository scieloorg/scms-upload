"""
Controller for Crossref DOI deposit operations.
"""

import logging
import sys

import requests
from lxml import etree
from packtools.sps.formats import crossref as crossref_format
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from tracker.models import UnexpectedEvent

logger = logging.getLogger(__name__)

CROSSREF_DEPOSIT_URL = "https://doi.crossref.org/servlet/deposit"


class CrossrefDepositError(Exception):
    pass


class CrossrefConfigurationNotFoundError(Exception):
    pass


def get_crossref_xml(sps_pkg, crossref_config):
    """
    Gera o XML no formato Crossref a partir de um SPSPkg.

    Parameters
    ----------
    sps_pkg : SPSPkg
        O pacote SPS do artigo.
    crossref_config : CrossrefConfiguration
        A configuração Crossref do periódico.

    Returns
    -------
    str
        O XML gerado no formato Crossref como string.

    Raises
    ------
    CrossrefDepositError
        Se não for possível gerar o XML.
    """
    try:
        xml_with_pre = sps_pkg.xml_with_pre
        if xml_with_pre is None:
            raise CrossrefDepositError(
                f"Could not get XML from package {sps_pkg}"
            )

        xml_tree = xml_with_pre.xmltree

        data = {
            "depositor_name": crossref_config.depositor_name,
            "depositor_email_address": crossref_config.depositor_email,
            "registrant": crossref_config.registrant,
        }

        if crossref_config.crossmark_policy_doi:
            data["crossmark_policy_doi"] = crossref_config.crossmark_policy_doi

        if crossref_config.crossmark_policy_url:
            data["crossmark_policy_url"] = crossref_config.crossmark_policy_url

        xml_crossref_str = crossref_format.pipeline_crossref(xml_tree, data)
        return xml_crossref_str

    except CrossrefDepositError:
        raise
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        raise CrossrefDepositError(
            f"Failed to generate Crossref XML for {sps_pkg}: {e}"
        ) from e


def deposit_xml_to_crossref(xml_content, crossref_config):
    """
    Realiza o depósito do XML no sistema do Crossref via HTTP.

    Parameters
    ----------
    xml_content : str
        O conteúdo do XML Crossref a ser depositado.
    crossref_config : CrossrefConfiguration
        A configuração Crossref do periódico (inclui credenciais).

    Returns
    -------
    tuple
        (status_code: int, response_body: str)

    Raises
    ------
    CrossrefDepositError
        Se não houver credenciais configuradas ou ocorrer erro de rede.
    """
    if not crossref_config.login_id or not crossref_config.login_password:
        raise CrossrefDepositError(
            f"Crossref login credentials are not configured for {crossref_config.journal}"
        )

    try:
        filename = f"crossref_{crossref_config.journal.journal_acron}.xml"
        files = {
            "fname": (
                filename,
                xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content,
                "text/xml",
            )
        }
        data = {
            "operation": "doMDUpload",
            "login_id": crossref_config.login_id,
            "login_passwd": crossref_config.login_password,
        }

        response = requests.post(
            CROSSREF_DEPOSIT_URL,
            data=data,
            files=files,
            timeout=60,
        )
        return response.status_code, response.text

    except requests.RequestException as e:
        raise CrossrefDepositError(
            f"Network error during Crossref deposit: {e}"
        ) from e


def deposit_article_doi(user, article, force=False):
    """
    Deposita o DOI de um artigo no Crossref.

    Parameters
    ----------
    user : User
        O usuário que está realizando o depósito.
    article : Article
        O artigo cujo DOI será depositado.
    force : bool
        Se True, realiza o depósito mesmo que já tenha sido feito com sucesso.

    Returns
    -------
    CrossrefDeposit
        O registro de depósito criado/atualizado.

    Raises
    ------
    CrossrefConfigurationNotFoundError
        Se não houver configuração Crossref para o periódico do artigo.
    CrossrefDepositError
        Se ocorrer erro durante o processo de depósito.
    """
    from doi.models import CrossrefConfiguration, CrossrefDeposit, CrossrefDepositStatus

    if not article.journal:
        raise CrossrefDepositError(
            f"Article {article} has no associated journal"
        )

    try:
        crossref_config = CrossrefConfiguration.get(journal=article.journal)
    except CrossrefConfiguration.DoesNotExist:
        raise CrossrefConfigurationNotFoundError(
            f"No Crossref configuration found for journal {article.journal}"
        )

    if not article.sps_pkg:
        raise CrossrefDepositError(
            f"Article {article} has no associated SPS package"
        )

    if not force:
        existing = CrossrefDeposit.objects.filter(
            article=article,
            status=CrossrefDepositStatus.SUCCESS,
        ).first()
        if existing:
            logger.info(
                f"Article {article} already has a successful Crossref deposit. "
                f"Use force=True to re-deposit."
            )
            return existing

    xml_content = get_crossref_xml(article.sps_pkg, crossref_config)

    deposit = CrossrefDeposit.create(user=user, article=article, xml_content=xml_content)

    try:
        status_code, response_body = deposit_xml_to_crossref(xml_content, crossref_config)

        if status_code in (200, 202):
            deposit.mark_success(
                response_status=status_code,
                response_body=response_body,
            )
        else:
            deposit.mark_error(
                response_status=status_code,
                response_body=response_body,
            )
    except CrossrefDepositError as e:
        deposit.mark_error(response_body=str(e))
        raise

    return deposit
