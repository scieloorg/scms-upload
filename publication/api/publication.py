import logging
import sys

from django.utils.translation import gettext_lazy as _

from core.utils.requester import post_data
from publication.api import exceptions


class PublicationAPI:
    """
    Interface com o site
    """

    def __init__(
        self,
        post_data_url=None,
        get_token_url=None,
        username=None,
        password=None,
        timeout=None,
    ):
        self.timeout = timeout or 15
        self.post_data_url = post_data_url
        self.get_token_url = get_token_url
        self.username = username
        self.password = password

    def post_data(self, payload):
        """
        name : str
            nome do arquivo xml
        """
        try:
            token = self._get_token()
            return self._post_data(payload, token)
        except (
            exceptions.GetAPITokenError,
            exceptions.APIPostDataError,
        ) as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            return {
                "error_msg": str(e),
                "error_type": str(type(e)),
                "traceback": [
                    str(item) for item in traceback.extract_tb(exc_traceback)
                ],
            }

    def _get_token(self):
        """
        curl -X POST 127.0.0.1:8000/api-token-auth/ \
            --data 'username=x&password=x'
        """
        if not self.get_token_url:
            return

        try:
            resp = post_data(
                self.get_token_url,
                data={"username": self.username, "password": self.password},
                auth=HTTPBasicAuth(self.username, self.password),
                timeout=self.timeout,
                json=True,
            )
            logging.info(resp)
            return resp.get("access")
        except Exception as e:
            # TODO tratar as exceções
            logging.exception(e)
            raise exceptions.GetAPITokenError(
                _("Unable to get api token {} {} {}").format(
                    self.username,
                    type(e),
                    e,
                )
            )

    def _post_data(self, payload, token):
        """
        payload : dict
        token : str

        curl -X POST -S \
            -H "Content-Disposition: attachment;filename=arquivo.zip" \
            -F "file=@path/arquivo.zip;type=application/zip" \
            -H 'Authorization: Bearer eyJ0b2tlb' \
            http://localhost:8000/api/v2/pid/pid_provider/ --output output.json
        """
        if token:
            header = {
                "Authorization": "Bearer " + token,
                # "content-type": "multi-part/form-data",
                # "Content-Disposition": "attachment; filename=%s" % basename,
            }
        else:
            header = {}
        try:
            logging.info(self.post_data_url)
            return post_data(
                self.post_data_url,
                data=payload,
                headers=header,
                timeout=self.timeout,
                verify=False,
                json=True,
            )
        except Exception as e:
            logging.exception(e)
            raise exceptions.APIPostDataError(
                _("Unable to post data {} {} {}").format(
                    payload,
                    type(e),
                    e,
                )
            )
