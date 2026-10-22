from pathlib import Path
from unittest.mock import patch

import pytest
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from pid_provider.base_pid_provider import BasePidProvider
from pid_provider.models import PidProviderXML, XMLVersion
from tracker.models import UnexpectedEvent


XML_PATH = Path(__file__).parents[1] / "fixtures/adendo/adendo_01.xml"
XML_URL = "https://www.scielo.br/article.xml"


@pytest.fixture
def data(db, django_user_model, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    user = django_user_model.objects.create_user(username="opac-xml")
    xml = list(XMLWithPre.create(xml_content=XML_PATH.read_text()))[0]
    return user, xml


def test_matching_pid_preserves_identity_and_xml_history(data):
    user, xml = data
    updated_xml = list(XMLWithPre.create(xml_content=XML_PATH.read_text().replace(
        "<article-title>Adendo</article-title>", "<article-title>Adendo atualizado</article-title>"
    )))[0]
    provider = BasePidProvider()
    with patch("pid_provider.base_pid_provider.XMLWithPre.create", side_effect=[[xml], [updated_xml]]):
        results = [provider.provide_pid_for_xml_uri(
            XML_URL, "adendo", user, expected_pid_v3=xml.v3,
            origin_date=date, force_update=True,
        ) for date in ("2026-01-01", "2026-02-01")]

    record = PidProviderXML.objects.get()
    assert all(result["v3"] == xml.v3 for result in results)
    assert record.v3 == xml.v3
    assert XMLVersion.objects.filter(pid_provider_xml=record).count() == 2
    assert not UnexpectedEvent.objects.exists()


def test_uri_rejects_mismatching_pid_before_registration(data):
    user, xml = data
    with patch("pid_provider.base_pid_provider.XMLWithPre.create", return_value=[xml]), patch.object(
        PidProviderXML, "register"
    ) as register:
        result = BasePidProvider().provide_pid_for_xml_uri(XML_URL, "adendo", user, expected_pid_v3="OTHER")

    register.assert_not_called()
    assert not PidProviderXML.objects.exists()
    assert not XMLVersion.objects.exists()
    assert "PID v3 mismatch" in result["error_msg"]
    event = UnexpectedEvent.objects.get()
    assert event.item == "OTHER"
    assert event.detail["stage"] == "pid_v3_mismatch"


def test_download_failure_returns_error(data):
    user, _ = data
    with patch("pid_provider.base_pid_provider.XMLWithPre.create", side_effect=OSError("unavailable")):
        result = BasePidProvider().provide_pid_for_xml_uri(XML_URL, "adendo", user)

    assert "unavailable" in result["error_msg"]
    assert UnexpectedEvent.objects.get().detail["stage"] == "xml_fetch_failed"


def test_zip_identification_failure_is_returned_by_generator(data):
    with patch("pid_provider.base_pid_provider.XMLWithPre.create", side_effect=OSError("unavailable")):
        results = list(BasePidProvider.is_registered_xml_zip("invalid.zip"))

    assert len(results) == 1 and "unavailable" in results[0]["error_msg"]
    assert UnexpectedEvent.objects.get().detail["operation"] == "PidProvider.is_registered_xml_zip"


@pytest.mark.parametrize("caller", [None, "core"])
def test_local_pid_reference_is_not_exposed_to_core(data, caller):
    user, xml = data
    with patch.object(PidProviderXML, "register", return_value={"ppx_id": 99, "v3": xml.v3}):
        result = BasePidProvider().provide_pid_for_xml_with_pre(xml, "sample.xml", user, caller=caller)

    assert ("ppx_id" in result) == (caller is None)
