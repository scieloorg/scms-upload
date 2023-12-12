import json
import logging
import sys
import traceback
import urllib

from django.utils.translation import gettext_lazy as _
from requests import HTTPError
from requests.auth import HTTPBasicAuth

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
        token=None,
    ):
        self.timeout = timeout or 15
        self.post_data_url = post_data_url
        self.get_token_url = get_token_url
        self.username = username
        self.password = password
        self.token = token

    @property
    def data(self):
        return dict(
            post_data_url=self.post_data_url,
            get_token_url=self.get_token_url,
            username=self.username,
            password=self.password,
        )

    def post_data(self, payload, kwargs=None):
        """
        payload : dict
        """
        logging.info(f"payload={payload}")
        response = None
        try:
            self.token = self.token or self.get_token()
            response = self._post_data(payload, self.token, kwargs)
        except HTTPError as e:
            if e.code == 401:
                response = self._get_token_and_post_data(payload, kwargs)
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
        logging.info(f"API OPAC payload={payload}")
        logging.info(f"API OPAC response: {response}")
        if response.get("id") and response.get("failed") is False:
            response["result"] = "OK"
        return response or {}

    def _get_token_and_post_data(self, payload, kwargs=None):
        """
        payload : dict
        """
        try:
            self.token = self.token or self.get_token()
            return self._post_data(payload, self.token, kwargs)
        except (
            exceptions.GetAPITokenError,
            exceptions.APIPostDataError,
        ) as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            logging.info(payload)
            return {
                "error_msg": str(e),
                "error_type": str(type(e)),
                "traceback": [
                    str(item) for item in traceback.extract_tb(exc_traceback)
                ],
            }

    def get_token(self):
        """
        curl -X POST 127.0.0.1:8000/api/v1/auth \
            --data 'username=x&password=x'
        """
        if not self.get_token_url:
            return

        try:
            resp = post_data(
                self.get_token_url,
                # data={"username": self.username, "password": self.password},
                auth=(self.username, self.password),
                timeout=self.timeout,
                json=True,
            )
            logging.info(resp)
            return resp.get("token")
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

    def _post_data(self, payload, token, kwargs=None):
        """
        payload : dict
        token : str

        curl -X POST -S \
            -H 'Authorization: Basic eyJ0b2tlb' \
            http://localhost:8000/api/v1/journal/
        """
        if token:
            header = {
                "Authorization": "Basic " + token,
                "Content-Type": "application/json",
            }
        else:
            header = {}
        try:
            logging.info(self.post_data_url)
            if kwargs:
                params = "&" + urllib.parse.urlencode(kwargs)
            else:
                params = ""
            return post_data(
                f"{self.post_data_url}/?token={token}{params}",
                data=json.dumps(payload),
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
