import logging

from django.utils.translation import gettext as _
from packtools.sps.pid_provider.xml_sps_lib import (
    XMLWithPre,
)

from pid_provider.models import PidProviderXML
from pid_provider.client import PidProviderAPIClient


LOGGER = logging.getLogger(__name__)
LOGGER_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class PidProvider:
    """
    Solicitar o PID da versão 3 para o Pid Provider e
    armazena o XML
    """

    def __init__(self):
        self.pid_provider_api = PidProviderAPIClient()

    def provide_pid_for_xml_zip(self, zip_xml_file_path, user, is_published=None):
        """
        Recebe um zip de arquivo XML para solicitar o PID da versão 3
        para o Pid Provider

        Returns
        -------
            list of dict
        """
        try:
            for xml_with_pre in XMLWithPre.create(path=zip_xml_file_path):
                logging.info("provide_pid_for_xml_zip:")
                try:
                    registered = self.provide_pid_for_xml_with_pre(
                        xml_with_pre,
                        xml_with_pre.filename,
                        user,
                        is_published,
                    )
                    registered["filename"] = xml_with_pre.filename
                    logging.info(registered)
                    yield registered
                except Exception as e:
                    logging.exception(e)
                    yield {
                        "error_msg": f"Unable to provide pid for {zip_xml_file_path} {e}",
                        "error_type": str(type(e)),
                    }
        except Exception as e:
            logging.exception(e)
            yield {
                "error_msg": f"Unable to provide pid for {zip_xml_file_path} {e}",
                "error_type": str(type(e)),
            }

    def provide_pid_for_xml_uri(self, xml_uri, name, user, is_published=None):
        """
        Recebe um zip de arquivo XML para solicitar o PID da versão 3
        para o Pid Provider

        Returns
        -------
            dict
        """
        try:
            xml_with_pre = list(XMLWithPre.create(uri=xml_uri))[0]
        except Exception as e:
            logging.exception(e)
            return {
                "error_msg": f"Unable to provide pid for {xml_uri} {e}",
                "error_type": str(type(e)),
            }
        else:
            return self.provide_pid_for_xml_with_pre(
                xml_with_pre, name, user, is_published
            )

    def provide_pid_for_xml_with_pre(self, xml_with_pre, name, user, is_published=None):
        """
        Recebe um xml_with_pre para solicitar o PID da versão 3
        para o Pid Provider

        Se o xml_with_pre já está registrado local e remotamente,
        apenas retorna os dados registrados
        {
            'registered': {...},
            'required_local_registration': False,
            'required_remote_registration': False,
        }

        Caso contrário, solicita PID versão 3 para o Pid Provider e
        armazena o resultado
        """
        response = self.pre_registration(xml_with_pre)
        if response.get("required_local_registration"):
            registered = PidProviderXML.register(
                xml_with_pre,
                name,
                user,
                is_published,
                synchronized=bool(response.get("xml_uri")),
                error_type=response.get("error_type"),
                error_msg=response.get("error_msg"),
                traceback=response.get("traceback"),
            )
        else:
            registered = response.get("registered")
        registered["xml_with_pre"] = xml_with_pre
        logging.info(f"provide_pid_for_xml_with_pre result: {registered}")
        return registered

    @classmethod
    def is_registered_xml_with_pre(cls, xml_with_pre):
        """
        Returns
        -------
            {"error_type": "", "error_message": ""}
            or
            {
                "v3": self.v3,
                "v2": self.v2,
                "aop_pid": self.aop_pid,
                "xml_with_pre": self.xml_with_pre,
                "created": self.created.isoformat(),
                "updated": self.updated.isoformat(),
            }
        """
        return PidProviderXML.get_registered(xml_with_pre)

    @classmethod
    def is_registered_xml_uri(cls, xml_uri):
        """
        Returns
        -------
            {"error_type": "", "error_message": ""}
            or
            {
                "v3": self.v3,
                "v2": self.v2,
                "aop_pid": self.aop_pid,
                "xml_with_pre": self.xml_with_pre,
                "created": self.created.isoformat(),
                "updated": self.updated.isoformat(),
            }
        """
        xml_with_pre = XMLWithPre.create(uri=xml_uri)
        return cls.is_registered_xml_with_pre(xml_with_pre)

    @classmethod
    def is_registered_xml_zip(cls, zip_xml_file_path):
        """
        Returns
        -------
            list of dict
                {"error_type": "", "error_message": ""}
                or
                {
                "v3": self.v3,
                "v2": self.v2,
                "aop_pid": self.aop_pid,
                "xml_with_pre": self.xml_with_pre,
                "created": self.created.isoformat(),
                "updated": self.updated.isoformat(),
                }
        """
        for xml_with_pre in XMLWithPre.create(path=zip_xml_file_path):
            registered = cls.is_registered_xml_with_pre(xml_with_pre)
            registered["filename"] = xml_with_pre.filename
            yield registered

    @classmethod
    def get_xml_uri(cls, v3):
        """
        Retorna XML URI ou None
        """
        return PidProviderXML.get_xml_uri(v3)

    def pre_registration(self, xml_with_pre):
        # verifica a necessidade de registro local e/ou remoto

        demand = PidProviderXML.check_registration_demand(xml_with_pre)

        logging.info(f"demand={demand}")
        if demand.get("error_type"):
            return demand

        response = {}
        if demand["required_remote_registration"]:
            response = self.pid_provider_api.provide_pid(xml_with_pre, name)

        response.update(demand)
        return response

    def synchronize(self, user):
        """
        Identifica no pid provider local os registros que não
        estão sincronizados com o pid provider remoto (central) e
        faz a sincronização, registrando o XML local no pid provider remoto
        """
        if not self.pid_provider_api.pid_provider_api_post_xml:
            raise ValueError(
                _(
                    "Unable to synchronized data with central pid provider because API URI is missing"
                )
            )
        for item in PidProviderXML.unsynchronized:
            name = item.pkg_name
            xml_with_pre = item.xml_with_pre
            response = self.pid_provider_api.provide_pid(xml_with_pre, name)
            item.set_synchronized(user, **response)
