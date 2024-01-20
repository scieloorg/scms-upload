import logging
import sys

# from django.utils.translation import gettext as _

from pid_provider.base_pid_provider import BasePidProvider
from pid_provider.client import PidProviderAPIClient
from pid_provider.models import PidProviderXML


class PidProvider(BasePidProvider):
    """
    Recebe XML para validar ou atribuir o ID do tipo v3
    """

    def __init__(self):
        self.pid_provider_api = PidProviderAPIClient()

    def provide_pid_for_xml_with_pre(
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
        Recebe um xml_with_pre para solicitar o PID da versão 3
        """
        v3 = xml_with_pre.v3
        logging.info("")
        logging.info(f"xml_with_pre.v3: {xml_with_pre.v3}")
        resp = self.pre_registration(xml_with_pre, name)

        if not resp["registered_in_upload"]:
            # não está registrado em Upload, realizar registro
            registered = PidProviderXML.register(
                xml_with_pre,
                name,
                user,
                origin_date=origin_date,
                force_update=force_update,
                is_published=is_published,
                origin=origin,
                registered_in_core=resp.get("registered_in_core"),
            )
            logging.info(f"PidProviderXML.register xml_with_pre.v3: {xml_with_pre.v3}")
            registered = registered or {}
            resp["registered_in_upload"] = bool(registered.get("v3"))
            resp.update(registered)
            logging.info(f"PidProviderXML.register registered: {registered}")
            logging.info(f"PidProviderXML.register resp: {resp}")

        resp["synchronized"] = (
            resp["registered_in_core"] and resp["registered_in_upload"]
        )
        resp["xml_with_pre"] = xml_with_pre
        resp["filename"] = name
        logging.info(f"PidProvider.provide_pid_for_xml_with_pre: resp={resp}")
        logging.info(f"PidProvider.provide_pid_for_xml_with_pre: v3={xml_with_pre.v3}")
        return resp

    def pre_registration(self, xml_with_pre, name):
        """
        Verifica a necessidade de registro no Upload e/ou Core
        Se aplicável, faz registro no Core
        Se aplicável, informa necessidade de registro no Upload

        Returns
        -------
        {'filename': '1518-8787-rsp-38-suppl-65.xml',
        'origin': '/app/core/media/1518-8787-rsp-38-suppl-65_wScfJap.zip',
        'v3': 'Lfh9K7RWn4Wt9XFfx3dY8vj',
        'v2': 'S0034-89102004000700010',
        'aop_pid': None,
        'pkg_name': '1518-8787-rsp-38-suppl-65',
        'created': '2024-01-16T19:35:21.454225+00:00',
        'updated': '2024-01-18T21:33:11.805681+00:00',
        'record_status': 'updated',
        'xml_changed': False}

        ou

        {"error_type": "ERROR ..."}

        """
        # retorna os dados se está registrado e é igual a xml_with_pre
        logging.info(f"xml_with_pre.v3 inicio: {xml_with_pre.v3}")
        registered = PidProviderXML.is_registered(xml_with_pre)

        if registered.get("error_type"):
            return registered

        registered = registered or {}

        pid_v3 = registered.get("v3")

        registered["registered_in_upload"] = bool(pid_v3)
        registered["registered_in_core"] = registered.get("registered_in_core")

        logging.info(f"PidProviderXML situacao: {registered}")

        if not registered["registered_in_core"]:
            # registra em Core
            response = self.pid_provider_api.provide_pid(xml_with_pre, name)
            logging.info(f"core pid provider xml_with_pre.v3: {xml_with_pre.v3}")
            if response.get("v3"):
                # está registrado em core
                registered.update(response)
                registered["registered_in_core"] = True

                logging.info(f"PidProviderXML situacao apos core: {registered}")
        return registered
