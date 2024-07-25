import logging
import sys

from django.db.models import Q
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from pid_provider.base_pid_provider import BasePidProvider
from pid_provider.client import PidProviderAPIClient
from pid_provider.models import FixPidV2, PidProviderXML
from tracker.models import UnexpectedEvent


class PidRequester(BasePidProvider):
    """
    Uso exclusivo da aplicação Upload
    Realiza solicitações para Pid Provider do Core
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
                yield self.request_pid_for_xml_with_pre(
                    xml_with_pre,
                    xml_with_pre.filename,
                    user,
                    origin_date=origin_date,
                    force_update=force_update,
                    is_published=is_published,
                    origin=zip_xml_file_path,
                    article_proc=article_proc,
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
        article_proc=None,
    ):
        """
        Recebe um xml_with_pre para solicitar o PID v3
        """
        # identifica as mudanças no xml_with_pre
        xml_changed = {}

        main_op = article_proc.start(user, "request_pid_for_xml_with_pre")
        registered = PidRequester.get_registration_demand(
            xml_with_pre, article_proc, user
        )

        if registered.get("error_type"):
            main_op.finish(user, completed=False, detail=registered)
            return registered

        # Solicita pid para Core
        self.core_registration(xml_with_pre, registered, article_proc, user)
        xml_changed = xml_changed or registered.get("xml_changed")

        # Atualiza registro de Upload
        if registered["do_upload_registration"] or xml_changed:
            # Cria ou atualiza registro de PidProviderXML de Upload, se:
            # - está registrado no upload mas o conteúdo mudou, atualiza
            # - ou não está registrado no Upload, então cria
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
                completed=registered["registered_in_upload"],
                detail={"registered": registered, "response": resp},
            )

        registered["synchronized"] = registered.get(
            "registered_in_core"
        ) and registered.get("registered_in_upload")
        registered["xml_changed"] = xml_changed
        registered["xml_with_pre"] = xml_with_pre
        registered["filename"] = name

        detail = registered.copy()
        detail["xml_with_pre"] = xml_with_pre.data
        main_op.finish(user, completed=registered["synchronized"], detail=detail)
        return registered

    @staticmethod
    def get_registration_demand(xml_with_pre, article_proc, user):
        """
        Obtém a indicação de demanda de registro no Upload e/ou Core

        Returns
        -------
        {"do_core_registration": boolean, "do_upload_registration": boolean}

        """
        op = article_proc.start(user, ">>> get registration demand")

        registered = PidProviderXML.is_registered(xml_with_pre)
        if registered.get("error_type"):
            op.finish(user, completed=False, detail=registered)
            return registered

        if registered.get("is_equal"):
            # xml recebido é igual ao registrado
            registered["do_core_registration"] = not registered.get(
                "registered_in_core"
            )
            registered["do_upload_registration"] = registered["do_core_registration"]
        else:
            # xml recebido é diferente ao registrado ou não está no upload
            registered["do_core_registration"] = True
            registered["do_upload_registration"] = True

        op.finish(user, completed=True, detail=registered)

        return registered

    def core_registration(self, xml_with_pre, registered, article_proc, user):
        """
        Solicita PID v3 para o Core, se necessário
        """
        if registered["do_core_registration"]:

            registered["registered_in_core"] = False

            op = article_proc.start(user, ">>> core registration")

            if not self.pid_provider_api.enabled:
                op.finish(user, completed=False, detail={"core_pid_provider": "off"})
                return registered

            if registered.get("v3") and not xml_with_pre.v3:
                raise ValueError(
                    f"Unable to execute core registration for xml_with_pre without v3"
                )

            response = self.pid_provider_api.provide_pid(
                xml_with_pre, xml_with_pre.filename, created=registered.get("created")
            )

            response = response or {}
            registered.update(response)
            registered["registered_in_core"] = bool(response.get("v3"))
            op.finish(
                user,
                completed=registered["registered_in_core"],
                detail={"registered": registered, "response": response},
            )

    def fix_pid_v2(
        self,
        user,
        pid_v3,
        correct_pid_v2,
    ):
        """
        Corrige pid_v2
        """
        fixed = {
            "pid_v3": pid_v3,
            "correct_pid_v2": correct_pid_v2,
        }

        try:
            pid_provider_xml = PidProviderXML.objects.get(
                v3=pid_v3, v2__contains=correct_pid_v2[:14]
            )
            fixed["pid_v2"] = pid_provider_xml.v2
        except PidProviderXML.DoesNotExist:
            return fixed
        except PidProviderXML.MultipleObjectsReturned:
            return fixed
        try:
            item_to_fix = FixPidV2.get_or_create(user, pid_provider_xml, correct_pid_v2)
        except ValueError as e:
            return {
                "error_message": str(e),
                "error_type": str(type(e)),
                "pid_v3": pid_v3,
                "correct_pid_v2": correct_pid_v2,
            }

        if not item_to_fix.fixed_in_upload:
            # atualiza v2 em pid_provider_xml
            response = pid_provider_xml.fix_pid_v2(user, correct_pid_v2)
            fixed["fixed_in_upload"] = response.get("v2") == correct_pid_v2

        if not item_to_fix.fixed_in_core:
            # atualiza v2 em pid_provider_xml do CORE
            # core - fix pid v2
            response = self.pid_provider_api.fix_pid_v2(pid_v3, correct_pid_v2)
            logging.info(f"Resposta de Core.fix_pid_v2 {fixed}: {response}")
            fixed.update(response or {})

        fixed_in_upload = fixed.get("fixed_in_upload")
        fixed_in_core = fixed.get("fixed_in_core")
        if fixed_in_upload or fixed_in_core:
            obj = FixPidV2.create_or_update(
                user,
                pid_provider_xml=pid_provider_xml,
                incorrect_pid_v2=item_to_fix.incorrect_pid_v2,
                correct_pid_v2=item_to_fix.correct_pid_v2,
                fixed_in_core=fixed_in_core or item_to_fix.fixed_in_core,
                fixed_in_upload=fixed_in_upload or item_to_fix.fixed_in_upload,
            )
            fixed["fixed_in_upload"] = obj.fixed_in_upload
            fixed["fixed_in_core"] = obj.fixed_in_core
        logging.info(fixed)
        return fixed

    @staticmethod
    def set_registered_in_core(pid_v3, value):
        try:
            PidProviderXML.objects.filter(
                registered_in_core=bool(not value),
                v3=pid_v3,
            ).update(registered_in_core=value)
        except Exception as e:
            logging.exception(e)
