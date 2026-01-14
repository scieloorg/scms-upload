import json
import logging
import sys
import traceback
import urllib

from django.utils.translation import gettext_lazy as _

from collection.models import WebSiteConfiguration
from core.utils.requester import post_data


def get_api(collection, content_type, website_kind):
    api_data = collection.get_website_config(
        purpose=website_kind,
        content_type=content_type,
    )
    if api_data.get("enabled"):
        return PublicationAPI(**api_data).data
    return {"error": f"Website {collection} {website_kind} is not enabled ({api_data})"}


def get_api_data(collection, content_type, website_kind=None):
    try:
        return get_api(collection, content_type, website_kind)
    except WebSiteConfiguration.DoesNotExist:
        return {"error": f"Website does not exist: {collection} {website_kind}"}
    except Exception as e:
        return {"error": f"Unable to get API data for {content_type} {collection} {website_kind}: {type(e)} {e}"}


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
        enabled=None
    ):
        self.timeout = timeout or 15
        self.post_data_url = post_data_url
        self.get_token_url = get_token_url
        self.username = username
        self.password = password
        self.token = token
        self.enabled = enabled
        if not token and enabled:
            self.get_token()

    @property
    def data(self):
        return dict(
            post_data_url=self.post_data_url,
            get_token_url=self.get_token_url,
            username=self.username,
            password=self.password,
            token=self.token,
            enabled=self.enabled,
        )

    def post_data(self, payload, kwargs=None):
        """
        payload : dict
        """
        # logging.info(f"payload={payload}")
        response = None
        try:
            if not self.enabled:
                raise ValueError(_("Website enabled is False ({})").format(self.post_data_url))
            if not self.token:
                self.get_token()
            response = self._post_data(payload, self.token, kwargs)
            response = self.format_response(response, payload)
            if not response.get("result"):
                self.get_token()
                response = self._post_data(payload, self.token, kwargs)
                return self.format_response(response, payload)
            return response
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            response = {
                "post_data_url": self.post_data_url,
                "payload": json.dumps(payload),
                "traceback": traceback.format_tb(exc_traceback),
                "error": str(e),
                "error_type": str(type(e)),
            }
            return response

    def format_response(self, response, payload):
        if response.get("id") and response["id"] != "None":
            response["result"] = "OK"
        elif response.get("failed") is False:
            response["result"] = "OK"
        response["payload"] = json.dumps(payload)
        return response or {}

    def get_token(self):
        """
        curl --request POST http://0.0.0.0:8000/api/v1/auth -u "useremail:password"
        """
        if not self.get_token_url:
            return

        resp = post_data(
            self.get_token_url,
            # data={"username": self.username, "password": self.password},
            auth=(self.username, self.password),
            timeout=self.timeout,
            json=True,
        )
        # logging.info(resp)
        self.token = resp.get("token")
        return self.token

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

        # logging.info(self.post_data_url)
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


class JournalPublicationAPI(PublicationAPI):
    def __init__(
        self,
        post_data_url=None,
        get_token_url=None,
        username=None,
        password=None,
        timeout=None,
        token=None,
    ):
        super().__init__(
            post_data_url,
            get_token_url,
            username,
            password,
            timeout,
            token,
        )