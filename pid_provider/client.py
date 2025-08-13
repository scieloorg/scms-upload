import logging
import os
import sys
import traceback
from tempfile import TemporaryDirectory

from django.utils.translation import gettext as _
from packtools.sps.pid_provider.xml_sps_lib import (
    XMLWithPre,
    create_xml_zip_file,
    get_xml_with_pre,
)
from requests import HTTPError
from requests.auth import HTTPBasicAuth

from core.utils.requester import post_data
from pid_provider import exceptions
from pid_provider.models import PidProviderConfig

LOGGER = logging.getLogger(__name__)
LOGGER_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class IncorrectPidV2RegisteredInCoreException(Exception): ...


class PidProviderAPIClient:
    """
    Interface com o pid provider do Core
    """

    def __init__(
        self,
        pid_provider_api_post_xml=None,
        pid_provider_api_get_token=None,
        timeout=None,
        api_username=None,
        api_password=None,
    ):
        self.token = None
        self.pid_provider_api_post_xml = pid_provider_api_post_xml
        self.pid_provider_api_get_token = pid_provider_api_get_token
        self.api_username = api_username
        self.api_password = api_password
        self.timeout = timeout or 120

    @property
    def enabled(self):
        try:
            self.set_config()
            return bool(self.api_username and self.api_password)
        except (AttributeError, ValueError, TypeError):
            return False

    def set_config(self):
        try:
            config = PidProviderConfig.get_or_create()
            self.pid_provider_api_post_xml = config.pid_provider_api_post_xml
            self.pid_provider_api_get_token = config.pid_provider_api_get_token
            self.api_username = config.api_username
            self.api_password = config.api_password
            self.timeout = config.timeout or 120
        except PidProviderConfig.DoesNotExist:
            self.pid_provider_api_post_xml = None
            self.pid_provider_api_get_token = None
            self.api_username = None
            self.api_password = None
            self.timeout = 120

    @property
    def fix_pid_v2_url(self):
        if not hasattr(self, "_fix_pid_v2_url") or not self._fix_pid_v2_url:
            try:
                self._fix_pid_v2_url = self.pid_provider_api_post_xml.replace(
                    "/pid_provider", "/fix_pid_v2"
                )
            except AttributeError:
                self._fix_pid_v2_url = None
        return self._fix_pid_v2_url

    def provide_pid_and_handle_incorrect_pid_v2(self, xml_with_pre, registered):
        try:
            return self.provide_pid(
                xml_with_pre,
                xml_with_pre.filename,
                created=registered.get("created"),
            )
        except IncorrectPidV2RegisteredInCoreException as e:
            # conserta valor de pid v2 no core
            fix_pid_v2_response = self.fix_pid_v2(
                xml_with_pre.v3, xml_with_pre.v2
            )
            if not fix_pid_v2_response or not fix_pid_v2_response.get(
                "fixed_in_core"
            ):
                raise IncorrectPidV2RegisteredInCoreException(
                    f"Unable to fix pid v2 {e}: fix_pid_v2_response={fix_pid_v2_response}"
                )
            # tenta novamente registrar pid no core
            return self.provide_pid(
                xml_with_pre,
                xml_with_pre.filename,
                created=registered.get("created"),
            )

    def provide_pid(self, xml_with_pre, name, created=None):
        """
        name : str
            nome do arquivo xml
        """
        try:
            self.token = self.token or self._get_token(
                username=self.api_username,
                password=self.api_password,
                timeout=self.timeout,
            )
            response = self._prepare_and_post_xml(xml_with_pre, name, self.token)
            self._process_post_xml_response(response[0], xml_with_pre, created)
            return response[0]
        except Exception as e:
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
            resp = None
            resp = post_data(
                self.pid_provider_api_get_token,
                data={"username": username, "password": password},
                auth=HTTPBasicAuth(username, password),
                timeout=timeout,
                json=True,
            )
            return resp["access"]
        except Exception as e:
            raise exceptions.GetAPITokenError(
                _("Unable to get api token {} {} {} {} {}").format(
                    self.pid_provider_api_get_token,
                    self.api_username,
                    type(e),
                    e,
                    resp,
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

            create_xml_zip_file(
                zip_xml_file_path, xml_with_pre.tostring(pretty_print=True)
            )
            response = self._post_xml(zip_xml_file_path, self.token, self.timeout)
            if isinstance(response, list):
                return response

            try:
                if response["code"] == "token_not_valid":
                    self.token = self._get_token(
                        username=self.api_username,
                        password=self.api_password,
                        timeout=self.timeout,
                    )
                    return self._post_xml(zip_xml_file_path, self.token, self.timeout)
            except TypeError:
                return None

    def _post_xml(self, zip_xml_file_path, token, timeout):
        """
        curl -X POST -S \
            -H "Content-Disposition: attachment;filename=arquivo.zip" \
            -F "file=@path/arquivo.zip;type=application/zip" \
            -H 'Authorization: Bearer eyJ0b2tlb' \
            http://localhost:8000/api/v2/pid/pid_provider/ --output output.json
        """
        try:
            basename = os.path.basename(zip_xml_file_path)

            with open(zip_xml_file_path, "rb") as fp:
                files = {
                    "file": (
                        basename,
                        fp,
                        "application/zip",
                    )
                }
                header = {
                    "Authorization": "Bearer " + token,
                    "content-type": "multi-part/form-data",
                    "Content-Disposition": "attachment; filename=%s" % basename,
                }
                return post_data(
                    self.pid_provider_api_post_xml,
                    files=files,
                    headers=header,
                    timeout=timeout,
                    verify=False,
                    json=True,
                )
        except Exception as e:
            raise exceptions.APIPidProviderPostError(
                _("Unable to get pid from pid provider {} {} {} {}").format(
                    self.pid_provider_api_post_xml,
                    zip_xml_file_path,
                    type(e),
                    e,
                )
            )

    def _process_post_xml_response(self, response, xml_with_pre, created=None):
        if not response:
            return
        try:
            self.is_pid_v2_correct_registered_in_core(
                xml_with_pre, response.get("xml_changed")
            )
            self._process_item_response(response, xml_with_pre, created)
        except AttributeError:
            raise ValueError(f"Unexpected pid provider response: {response}")

    def is_pid_v2_correct_registered_in_core(self, xml_with_pre, xml_changed):
        if xml_changed:
            if len(xml_changed) == 1 and xml_changed.get("pid_v2"):
                raise IncorrectPidV2RegisteredInCoreException(
                    f"incorrect in core: {xml_changed} x correct={xml_with_pre.data}"
                )
        return True

    def _process_item_response(self, item, xml_with_pre, created=None):
        if not item.get("xml_changed"):
            # pids do xml_with_pre não mudaram
            return
        for pid_type, pid_value in item["xml_changed"].items():
            if pid_type == "pid_v3":
                xml_with_pre.v3 = pid_value
                continue
            if pid_type == "pid_v2":
                xml_with_pre.v2 = pid_value
                continue
            if pid_type == "aop_pid":
                xml_with_pre.aop_pid = pid_value
                continue
        return

    def fix_pid_v2(self, pid_v3, correct_pid_v2):
        """
        name : str
            nome do arquivo xml
        """
        try:
            if not self.fix_pid_v2_url:
                return {"fix-pid-v2": "unavailable", "fixed_in_core": False}

            self.token = self.token or self._get_token(
                username=self.api_username,
                password=self.api_password,
                timeout=self.timeout,
            )
            response = self._post_fix_pid_v2(
                pid_v3, correct_pid_v2, self.token, self.timeout
            )
            response["fixed_in_core"] = response.get("v2") == correct_pid_v2
            return response
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

    def _post_fix_pid_v2(self, pid_v3, correct_pid_v2, token, timeout):
        header = {
            "Authorization": "Bearer " + token,
            # "content-type": "multi-part/form-data",
            # "content-type": "application/json",
        }
        try:
            uri = self.fix_pid_v2_url
            return post_data(
                uri,
                data={"pid_v3": pid_v3, "correct_pid_v2": correct_pid_v2},
                headers=header,
                timeout=timeout,
                verify=False,
                json=True,
            )
        except Exception as e:
            logging.exception(e)
            raise exceptions.APIPidProviderFixPidV2Error(
                _("Unable to get pid from pid provider {} {} {} {} {}").format(
                    uri,
                    pid_v3,
                    correct_pid_v2,
                    type(e),
                    e,
                )
            )
