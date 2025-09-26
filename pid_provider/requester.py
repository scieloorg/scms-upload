import logging
import sys

from django.db.models import Q
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from pid_provider.base_pid_provider import BasePidProvider
from pid_provider.client import (
    PidProviderAPIClient,
)
from pid_provider.models import FixPidV2, PidProviderXML
from tracker.models import UnexpectedEvent


def check_xml_changed(original, registered):
    for pid_type in ("v3", "v2", "aop_pid"):
        if original[pid_type] != registered.get(pid_type):
            return True
    return False


class CorePidProviderUnabledException(Exception):
    pass


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
        original = {
            "v3": xml_with_pre.v3,
            "v2": xml_with_pre.v2,
            "aop_pid": xml_with_pre.aop_pid,
        }
        registered = PidRequester.get_registration_demand(
            user, article_proc, xml_with_pre
        )
        if registered.get("error_type"):
            return registered

        # Solicita pid para Core
        remote_response = self.remote_registration(
            user, article_proc, xml_with_pre, registered)
        if registered.get("error_type"):
            return registered

        # Atualiza registro de Upload
        local_response = self.local_registration(
            user, article_proc, xml_with_pre, registered,
            origin_date, force_update, is_published, origin,
        )
        if registered.get("error_type"):
            return registered

        registered["xml_with_pre"] = xml_with_pre
        registered["filename"] = name
        registered["changed"] = check_xml_changed(original, registered)
        return registered

    @staticmethod
    def get_registration_demand(user, article_proc, xml_with_pre):
        """
        Obtém a indicação de demanda de registro no Upload e/ou Core.
        
        Parameters
        ----------
        xml_with_pre : XMLWithPre
            Objeto contendo os dados XML a serem analisados
        article_proc : ArticleProc
            Processador de artigo para controle de operações
        user : User
            Usuário executando a operação
        
        Returns
        -------
        dict
            {"do_remote_registration": bool, "do_local_registration": bool, ...}
        """
        # Inicia operação de logging para rastreamento
        op = article_proc.start(user, ">>> get registration demand")
        
        # Verifica se o XML já está registrado e obtém dados de comparação
        registered = PidProviderXML.is_registered(xml_with_pre)
        
        # Se houve erro na verificação, finaliza operação e retorna erro
        if registered.get("error_type"):
            op.finish(user, completed=False, detail=registered)
            return registered
        
        # Determina demanda de registro baseado na comparação
        if registered.get("is_equal"):
            # XML recebido é igual ao registrado
            # Só registra no Core se ainda não estiver registrado lá
            registered["do_remote_registration"] = not registered.get("registered_in_core")
            # Upload segue a mesma regra do Core quando XMLs são iguais
            registered["do_local_registration"] = registered["do_remote_registration"]
        else:
            # XML recebido é diferente do registrado ou não está no Upload
            # Força registro em ambos os sistemas
            registered["do_remote_registration"] = True
            registered["do_local_registration"] = True
        
        op.finish(user, completed=True, detail=registered)
        return registered

    def remote_registration(self, user, article_proc, xml_with_pre, registered):
        """
        Solicita PID v3 para o Core, se necessário
        """
        op = article_proc.start(user, ">>> core registration")

        if not registered["do_remote_registration"]:
            op.finish(user, completed=True, detail=registered)
            return {}

        try:
            if not self.pid_provider_api.enabled:
                raise CorePidProviderUnabledException(
                    "Core pid provider is not enabled. Complete core pid provider configuration to enable it")

            response = self.pid_provider_api.provide_pid_and_handle_incorrect_pid_v2(
                xml_with_pre, registered)

            if response.get("error_type"):
                op.finish(user, completed=False, detail=response)
                return response

            response["registered_in_core"] = True
            response["do_local_registration"] = True

            op.finish(
                user,
                completed=True,
                detail=response,
            )
            registered.update(response)
            return response
        except Exception as exc:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            op.finish(user, completed=False, exception=exc, exc_traceback=exc_traceback)
            return {"error_msg": str(exc), "error_type": str(type(exc))}
                
    def local_registration(self, user, article_proc, xml_with_pre, registered, origin_date, force_update, is_published, origin):
        # Atualiza registro de Upload
        try:
            op = article_proc.start(user, ">>> local registration")
            resp = {}
            detail = registered
            if registered["do_local_registration"]:
                # Cria ou atualiza registro de PidProviderXML de Upload, se:
                # - está registrado no upload mas o conteúdo mudou, atualiza
                # - ou não está registrado no Upload, então cria
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
                resp["registered_in_upload"] = bool(resp.get("v3"))
                resp["synchronized"] = registered.get(
                    "registered_in_core"
                ) and bool(resp.get("v3"))
                registered.update(resp)

                detail = resp
                
            op.finish(user, completed=True, detail=detail)
            return resp
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            op.finish(user, completed=False, exception=e, exc_traceback=exc_traceback)
            return {"error_msg": str(e), "error_type": str(type(e))}

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
