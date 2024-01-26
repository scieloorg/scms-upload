import logging
import sys
from zipfile import ZipFile

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
        article_proc=None,
    ):
        try:
            for xml_with_pre in XMLWithPre.create(path=zip_xml_file_path):
                response = self.request_pid_for_xml_with_pre(
                    xml_with_pre,
                    xml_with_pre.filename,
                    user,
                    origin_date=origin_date,
                    force_update=force_update,
                    is_published=is_published,
                    origin=zip_xml_file_path,
                    article_proc=article_proc,
                )

                if response.get("xml_changed"):
                    # atualiza conteúdo de zip
                    with ZipFile(zip_xml_file_path, "a") as zf:
                        zf.writestr(
                            xml_with_pre.filename,
                            xml_with_pre.tostring(pretty_print=True),
                        )
                yield response
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
        article_proc=None,
    ):
        """
        Recebe um xml_with_pre para solicitar o PID v3
        """
        main_op = article_proc.start(user, "request_pid_for_xml_with_pre")
        registered = PidRequester.get_registration_demand(
            xml_with_pre, article_proc, user
        )

        if registered.get("error_type"):
            return registered

        self.core_registration(xml_with_pre, registered, article_proc, user)
        xml_changed = registered.get("xml_changed")

        if not registered["registered_in_upload"]:
            # não está registrado em Upload, realizar registro

            op = article_proc.start(user, ">>> upload registration")
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
            xml_changed = xml_changed or resp.get("xml_changed")
            registered.update(resp)
            registered["registered_in_upload"] = bool(resp.get("v3"))
            op.finish(
                user,
                completed=True,
                detail={"registered": registered, "response": resp},
            )

        registered["synchronized"] = (
            registered["registered_in_core"] and registered["registered_in_upload"]
        )
        registered["xml_changed"] = xml_changed
        registered["xml_with_pre"] = xml_with_pre
        registered["filename"] = name

        main_op.finish(user, completed=True, detail={"registered": registered})
        return registered

    @staticmethod
    def get_registration_demand(xml_with_pre, article_proc, user):
        """
        Obtém a indicação de demanda de registro no Upload e/ou Core

        Returns
        -------
        {"registered_in_upload": boolean, "registered_in_core": boolean}

        """
        op = article_proc.start(user, ">>> get registration demand")

        registered = PidProviderXML.is_registered(xml_with_pre) or {}
        registered["registered_in_upload"] = bool(registered.get("v3"))
        registered["registered_in_core"] = registered.get("registered_in_core")

        op.finish(user, completed=True, detail={"registered": registered})

        return registered

    def core_registration(self, xml_with_pre, registered, article_proc, user):
        """
        Solicita PID v3 para o Core, se necessário
        """
        if not registered["registered_in_core"]:
            op = article_proc.start(user, ">>> core registration")

            if not self.pid_provider_api.enabled:
                op.finish(user, completed=False, detail={"core_pid_provider": "off"})
                return registered

            response = self.pid_provider_api.provide_pid(
                xml_with_pre, xml_with_pre.filename
            )
            response = response or {}
            registered.update(response)
            registered["registered_in_core"] = bool(response.get("v3"))
            op.finish(
                user,
                completed=True,
                detail={"registered": registered, "response": response},
            )

        return registered
