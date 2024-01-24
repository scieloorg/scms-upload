import logging
import sys

from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from pid_provider.base_pid_provider import BasePidProvider
from pid_provider.client import PidProviderAPIClient
from pid_provider.models import PidProviderXML
from tracker.models import UnexpectedEvent


class PidRequester(BasePidProvider):
    """
    Recebe XML para validar ou atribuir o ID do tipo v3
    """

    def __init__(self):
        self.pid_provider_api = PidProviderAPIClient()

    def request_pid_for_xml_zip(
        self,
        zip_xml_file_path,
        user,
        filename=None,
        origin_date=None,
        force_update=None,
        is_published=None,
    ):
        try:
            for xml_with_pre in XMLWithPre.create(path=zip_xml_file_path):
                yield self.request_pid_for_xml_with_pre(
                    xml_with_pre,
                    xml_with_pre.filename,
                    user,
                    origin_date=origin_date,
                    force_update=force_update,
                    is_published=is_published,
                    origin=zip_xml_file_path,
                )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                exception=e,
                exc_traceback=exc_traceback,
                detail={
                    "operation": "PidRequester.request_pid_for_xml_zip",
                    "input": dict(
                        zip_xml_file_path=zip_xml_file_path,
                        user=user.username,
                        filename=filename,
                        origin_date=origin_date,
                        force_update=force_update,
                        is_published=is_published,
                    ),
                },
            )
            yield {
                "error_msg": f"Unable to provide pid for {zip_xml_file_path} {e}",
                "error_type": str(type(e)),
            }

    def request_pid_for_xml_with_pre(
        self,
        xml_with_pre,
        name,
        user,
        origin_date=None,
        force_update=None,
        is_published=None,
        origin=None,
    ):
        """
        Recebe um xml_with_pre para solicitar o PID v3
        """
        v3 = xml_with_pre.v3
        logging.info(".................................")
        logging.info(f"PidRequester.request_pid_for_xml_with_pre: {xml_with_pre.v3}")

        registered = PidRequester.get_registration_demand(xml_with_pre)
        if registered.get("error_type"):
            return registered

        self.core_registration(xml_with_pre, registered)

        if not registered["registered_in_upload"]:
            # não está registrado em Upload, realizar registro
            resp = self.provide_pid_for_xml_with_pre(
                xml_with_pre,
                xml_with_pre.filename,
                user,
                origin_date=origin_date,
                force_update=force_update,
                is_published=is_published,
                origin=origin,
                registered_in_core=registered.get("registered_in_core"),
            )
            logging.info(f"upload registration: {resp}")
            registered.update(resp)
            logging.info(f"registered: {registered}")
            registered["registered_in_upload"] = bool(resp.get("v3"))
            logging.info(f"registered: {registered}")

        registered["synchronized"] = (
            registered["registered_in_core"] and registered["registered_in_upload"]
        )
        registered["xml_with_pre"] = xml_with_pre
        registered["filename"] = name
        logging.info(f"registered={registered}")
        logging.info(f"v3={xml_with_pre.v3}")
        return registered

    @staticmethod
    def get_registration_demand(xml_with_pre):
        """
        Obtém a indicação de demanda de registro no Upload e/ou Core

        Returns
        -------
        {"registered_in_upload": boolean, "registered_in_core": boolean}

        """
        registered = PidProviderXML.is_registered(xml_with_pre) or {}
        registered["registered_in_upload"] = bool(registered.get("v3"))
        registered["registered_in_core"] = registered.get("registered_in_core")
        logging.info(f"PidRequester.get_registration_demand: {registered}")
        return registered

    def core_registration(self, xml_with_pre, registered):
        """
        Solicita PID v3 para o Core, se necessário
        """
        if not self.pid_provider_api.enabled:
            return registered

        if not registered["registered_in_core"]:
            response = self.pid_provider_api.provide_pid(
                xml_with_pre, xml_with_pre.filename)
            response = response or {}
            registered.update(response)
            registered["registered_in_core"] = bool(response.get("v3"))
            logging.info(f"PidRequester.core_registration: {registered}")
        return registered
