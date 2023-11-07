import logging
import os
import sys
import traceback
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from packtools.sps.pid_provider.xml_sps_lib import (
    XMLWithPre,
    create_xml_zip_file,
    get_xml_with_pre,
)
from provides.auth import HTTPBasicAuth

from pid_provider import exceptions
from pid_provider.models import PidProviderConfig, PidProviderXML
from pid_provider.utils.provideer import post_data

User = get_user_model()

LOGGER = logging.getLogger(__name__)
LOGGER_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class PidProvider:
    """
    Solicitar o PID da versão 3 para o Pid Provider e
    armazena o XML
    """

    def __init__(self):
        self.pid_provider_api = PidProviderAPI()

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
        # verifica a necessidade de registro local e/ou remoto
        demand = PidProviderXML.check_registration_demand(xml_with_pre)

        logging.info(f"demand={demand}")
        if demand.get("error_type"):
            return demand

        response = {}
        registered = demand["registered"]

        if demand["required_remote_registration"]:
            response = self.pid_provider_api.provide_pid(xml_with_pre, name)

        if demand["required_local_registration"]:
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


class PidProviderAPI:
    """
    Interface com o pid provider
    """

    def __init__(
        self,
        pid_provider_api_post_xml=None,
        pid_provider_api_get_token=None,
        timeout=None,
        api_username=None,
        api_password=None,
    ):
        self.timeout = timeout or 15
        self._pid_provider_api_post_xml = pid_provider_api_post_xml
        self._pid_provider_api_get_token = pid_provider_api_get_token
        self._api_username = api_username
        self._api_password = api_password

    @property
    def config(self):
        if not hasattr(self, "_config") or not self._config:
            try:
                self._config = PidProviderConfig.get_or_create()
            except Exception as e:
                logging.exception(f"PidProviderConfig.get_or_create {e}")
                self._config = None
        return self._config

    @property
    def pid_provider_api_post_xml(self):
        if self._pid_provider_api_post_xml is None:
            try:
                self._pid_provider_api_post_xml = self.config.pid_provider_api_post_xml
            except AttributeError as e:
                raise exceptions.APIPidProviderConfigError(e)
        return self._pid_provider_api_post_xml

    @property
    def pid_provider_api_get_token(self):
        if self._pid_provider_api_get_token is None:
            try:
                self._pid_provider_api_get_token = (
                    self.config.pid_provider_api_get_token
                )
            except AttributeError as e:
                raise exceptions.APIPidProviderConfigError(e)
        return self._pid_provider_api_get_token

    @property
    def api_username(self):
        if self._api_username is None:
            try:
                self._api_username = self.config.api_username
            except AttributeError as e:
                raise exceptions.APIPidProviderConfigError(e)
        return self._api_username

    @property
    def api_password(self):
        if self._api_password is None:
            try:
                self._api_password = self.config.api_password
            except AttributeError as e:
                raise exceptions.APIPidProviderConfigError(e)
        return self._api_password

    def provide_pid(self, xml_with_pre, name):
        """
        name : str
            nome do arquivo xml
        """
        try:
            token = self._get_token(
                username=self.api_username,
                password=self.api_password,
                timeout=self.timeout,
            )
            response = self._prepare_and_post_xml(xml_with_pre, name, token)

            self._process_post_xml_response(response, xml_with_pre)
            try:
                return response[0]
            except IndexError:
                return
        except (
            exceptions.GetAPITokenError,
            exceptions.APIPidProviderPostError,
            exceptions.APIPidProviderConfigError,
        ) as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            return {
                "error_msg": str(e),
                "error_type": str(type(e)),
                "traceback": [
                    str(item) for item in traceback.extract_tb(exc_traceback)
                ],
            }

    def _get_token(self, username, password, timeout):
        """
        curl -X POST 127.0.0.1:8000/api-token-auth/ \
            --data 'username=x&password=x'
        """
        try:
            logging.info(self.pid_provider_api_get_token)
            resp = post_data(
                self.pid_provider_api_get_token,
                data={"username": username, "password": password},
                auth=HTTPBasicAuth(username, password),
                timeout=timeout,
                json=True,
            )
            logging.info(resp)
            return resp.get("access")
        except Exception as e:
            # TODO tratar as exceções
            logging.exception(e)
            raise exceptions.GetAPITokenError(
                _("Unable to get api token {} {} {} {}").format(
                    username,
                    password,
                    type(e),
                    e,
                )
            )

    def _prepare_and_post_xml(self, xml_with_pre, name, token):
        """
        name : str
            nome do arquivo xml
        """
        with TemporaryDirectory() as tmpdirname:
            name, ext = os.path.splitext(name)
            zip_xml_file_path = os.path.join(tmpdirname, name + ".zip")

            create_xml_zip_file(zip_xml_file_path, xml_with_pre.tostring())

            return self._post_xml(zip_xml_file_path, token, self.timeout)

    def _post_xml(self, zip_xml_file_path, token, timeout):
        """
        curl -X POST -S \
            -H "Content-Disposition: attachment;filename=arquivo.zip" \
            -F "file=@path/arquivo.zip;type=application/zip" \
            -H 'Authorization: Bearer eyJ0b2tlb' \
            http://localhost:8000/api/v2/pid/pid_provider/ --output output.json
        """
        basename = os.path.basename(zip_xml_file_path)

        files = {
            "file": (
                basename,
                open(zip_xml_file_path, "rb"),
                "application/zip",
            )
        }
        header = {
            "Authorization": "Bearer " + token,
            "content-type": "multi-part/form-data",
            "Content-Disposition": "attachment; filename=%s" % basename,
        }
        try:
            logging.info(self.pid_provider_api_post_xml)
            return post_data(
                self.pid_provider_api_post_xml,
                files=files,
                headers=header,
                timeout=timeout,
                verify=False,
                json=True,
            )
        except Exception as e:
            logging.exception(e)
            raise exceptions.APIPidProviderPostError(
                _("Unable to get pid from pid provider {} {} {}").format(
                    zip_xml_file_path,
                    type(e),
                    e,
                )
            )

    def _process_post_xml_response(self, response, xml_with_pre):
        logging.info(f"_process_post_xml_response: {response}")
        if not response:
            return
        for item in response:
            if not item.get("xml_changed"):
                return
            try:
                xml_with_pre = get_xml_with_pre(item["xml"])
            except KeyError:
                pass
            try:
                # atualiza xml_with_pre com valor do XML registrado no core
                for xml_with_pre in XMLWithPre.create(uri=item["xml_uri"]):
                    break
            except KeyError:
                pass
