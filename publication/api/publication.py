import copy
import json
import logging
import sys
import time
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


# Cache em processo para api_data (inclui token). Objetivo: solicitar token
# apenas 1x por (collection, content_type, website_kind) e revalidar somente
# quando expirar. Estratégia:
#   - TTL longo (alinhado ao lifetime típico de JWT) como teto de segurança,
#     evitando reter tokens indefinidamente em workers de longa duração;
#   - invalidação explícita via invalidate_api_data_cache(...) — chamadores
#     que detectarem falha de autenticação no PublicationAPI.post_data podem
#     purgar a entrada e forçar novo login na próxima chamada.
# Observação: PublicationAPI.post_data já refaz get_token() na própria
# instância ao receber falha, então um token expirado entre a leitura do
# cache e o uso resulta em 1 retry interno (não em erro propagado).
_API_DATA_CACHE = {}
_API_DATA_CACHE_TTL = 3600  # segundos (1h); ajustar via clear/invalidate se necessário


def _api_data_cache_key(collection, content_type, website_kind):
    return (getattr(collection, "pk", None), content_type, website_kind)


def clear_api_data_cache():
    """Limpa todo o cache em processo de api_data (uso em testes/admin)."""
    _API_DATA_CACHE.clear()


def invalidate_api_data_cache(collection, content_type, website_kind=None):
    """Invalida uma entrada específica do cache.

    Deve ser chamado por consumidores ao detectar falha de autenticação
    (token expirado/revogado) no resultado de PublicationAPI.post_data,
    para forçar novo login na próxima chamada de get_api_data.
    """
    _API_DATA_CACHE.pop(
        _api_data_cache_key(collection, content_type, website_kind), None
    )


def get_api_data(collection, content_type, website_kind=None):
    key = _api_data_cache_key(collection, content_type, website_kind)
    cached = _API_DATA_CACHE.get(key)
    now = time.time()
    if cached and now - cached[0] < _API_DATA_CACHE_TTL:
        # deepcopy: defesa contra mutação de estruturas aninhadas pelos
        # chamadores (ex.: api_data["verify"] = verify em task_publish_articles).
        return copy.deepcopy(cached[1])
    try:
        data = get_api(collection, content_type, website_kind)
    except WebSiteConfiguration.DoesNotExist:
        return {"error": f"Website does not exist: {collection} {website_kind}"}
    except Exception as e:
        return {"error": f"Unable to get API data for {content_type} {collection} {website_kind}: {type(e)} {e}"}
    if isinstance(data, dict) and not data.get("error") and key[0] is not None:
        _API_DATA_CACHE[key] = (now, copy.deepcopy(data))
    return data


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
        enabled=None,
        verify=False,
    ):
        self.timeout = timeout or 15
        self.post_data_url = post_data_url
        self.get_token_url = get_token_url
        self.username = username
        self.password = password
        self.token = token
        self.enabled = enabled
        self.verify = verify
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
            verify=self.verify,
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
            verify=self.verify,
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