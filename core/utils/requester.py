import logging
import re

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from urllib3.util import Retry

logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """Recoverable error without having to modify the data state on the client
    side, e.g. timeouts, errors from network partitioning, etc.
    """


class NonRetryableError(Exception):
    """Recoverable error without having to modify the data state on the client
    side, e.g. timeouts, errors from network partitioning, etc.
    """


def _add_param(params, name, value):
    if value:
        params[name] = value
    return params


@retry(
    retry=retry_if_exception_type(RetryableError),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    stop=stop_after_attempt(5),
)
def post_data(
    url,
    auth=None,
    data=None,
    files=None,
    headers=None,
    json=False,
    timeout=2,
    verify=True,
):
    """
    Post data with HTTP
    Retry: Wait 2^x * 1 second between each retry starting with 4 seconds,
           then up to 10 seconds, then 10 seconds afterwards
    Args:
        url: URL address
        files: files
        headers: HTTP headers
        json: True|False
        verify: Verify the SSL.
    Returns:
        Return a requests.response object.
    Except:
        Raise a RetryableError to retry.
    """
    try:
        logger.info("Posting data: %s" % url)
        params = dict(
            headers=headers,
            timeout=timeout,
            verify=verify,
        )
        params = _add_param(params, "auth", auth)
        params = _add_param(params, "files", files)
        params = _add_param(params, "data", data)
        logging.info(f"data={data}")
        for k, v in params.items():
        	logging.info(f"{k}={v}")
        response = requests.post(url, **params)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        logger.error("Erro posting data: %s, retry..., erro: %s" % (url, exc))
        raise RetryableError(exc) from exc
    except (
        requests.exceptions.InvalidSchema,
        requests.exceptions.MissingSchema,
        requests.exceptions.InvalidURL,
    ) as exc:
        raise NonRetryableError(exc) from exc
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if 400 <= exc.response.status_code < 500:
            raise NonRetryableError(exc) from exc
        elif 500 <= exc.response.status_code < 600:
            logger.error(
                "Erro fetching the content: %s, retry..., erro: %s" % (url, exc)
            )
            raise RetryableError(exc) from exc
        else:
            raise

    return response.content if not json else response.json()
