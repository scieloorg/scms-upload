from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from pid_provider.requester import PidRequester


@pytest.mark.parametrize("stage", ["remote", "local"])
@pytest.mark.parametrize("raises", [False, True])
def test_pid_request_stops_and_returns_registration_error(stage, raises):
    xml = SimpleNamespace(
        v3="existing-pid", v2=None, aop_pid=None, filename="article.xml"
    )
    registered = {
        "v3": xml.v3,
        "v2": None,
        "aop_pid": None,
        "registered_in_core": True,
        "do_remote_registration": True,
        "do_local_registration": True,
    }
    error = {"error_type": "RegistrationError", "error_msg": "registration failed"}
    remote = Mock(return_value={"v3": xml.v3})
    local = Mock(return_value={"v3": xml.v3})
    failing = remote if stage == "remote" else local
    if raises:
        failing.side_effect = RuntimeError(error["error_msg"])
    else:
        failing.return_value = error
    process = Mock()
    requester = PidRequester()
    requester.pid_provider_api = SimpleNamespace(
        enabled=True, provide_pid_and_handle_incorrect_pid_v2=remote
    )

    with patch.object(
        PidRequester, "get_registration_demand", return_value=registered
    ), patch.object(requester, "provide_pid_for_xml_with_pre", local):
        result = requester.request_pid_for_xml_with_pre(
            xml, xml.filename, Mock(), article_proc=process
        )

    assert result["error_type"]
    assert result["error_msg"] == error["error_msg"]
    assert "xml_with_pre" not in result
    assert process.start.return_value.finish.call_args.kwargs["completed"] is False
    if stage == "remote":
        local.assert_not_called()
