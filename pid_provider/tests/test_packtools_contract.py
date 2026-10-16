from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
from django.contrib.auth import get_user_model
from lxml import etree
from packtools.sps.pid_provider.xml_sps_adapter import PidProviderXMLAdapter
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from package.models import SPSPkg
from pid_provider.models import PidProviderXML, PidProviderXMLRegistration
from pid_provider.query_params import compare, get_data_to_compare
from upload.utils.package_utils import render_html


XML_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures/sub-article/2236-8906-hoehnea-49-e1082020.xml"
)


@pytest.fixture
def xml():
    return XMLWithPre("", etree.parse(str(XML_PATH)))


def test_new_records_and_adapter_use_same_comparison_fields(xml):
    adapter = PidProviderXMLAdapter(xml)
    record = PidProviderXML()
    record._add_data(adapter, registered_in_core=False)

    assert "partial_body" not in record.readable_data
    assert record.readable_data == xml.readable_data
    incoming = get_data_to_compare(adapter)
    assert record.data_to_compare == {
        key: value for key, value in incoming.items() if key != "pid_v2"
    }
    assert (
        compare(record.data_to_compare, incoming)[
            "percentual_score"
        ]
        == 1
    )


@pytest.mark.django_db
@pytest.mark.parametrize("legacy", [None, {"partial_body": "legacy"}])
def test_legacy_readable_data_is_cached_without_changing_registration_date(xml, legacy):
    user = get_user_model().objects.create_user(username="legacy-pid")
    record = PidProviderXML.objects.create(creator=user, readable_data=legacy)
    updated = record.updated
    with patch.object(
        PidProviderXML, "xml_with_pre", new_callable=PropertyMock, return_value=xml
    ):
        assert record.get_readable_data() == xml.readable_data

    record.refresh_from_db()
    assert record.readable_data == xml.readable_data
    assert record.updated == updated
    with patch.object(PidProviderXML, "xml_with_pre", new_callable=PropertyMock) as read:
        assert record.get_readable_data() == xml.readable_data
        read.assert_not_called()


def test_cached_legacy_titles_are_preserved_without_reopening_xml():
    record = PidProviderXML(readable_data={
        "partial_body": "legacy", "article_titles": ["Título registrado"]
    })
    with patch.object(PidProviderXML, "xml_with_pre", new_callable=PropertyMock) as read:
        assert record.data_to_compare["article_titles"] == ["Título registrado"]
        read.assert_not_called()

    assert record.readable_data == {"article_titles": ["Título registrado"]}


@pytest.mark.django_db
def test_unreadable_xml_uses_pid_v2_to_disambiguate_colliding_hashes(xml):
    xml.v2 = "S1234-56782026000100001"
    adapter = PidProviderXMLAdapter(xml)
    user = get_user_model().objects.create_user(username="unreadable-pid")
    correct = PidProviderXML.objects.create(
        creator=user, v2=xml.v2, z_surnames=adapter.z_surnames
    )
    other = PidProviderXML.objects.create(
        creator=user, v2="S1234-56782026000100002", z_surnames=adapter.z_surnames
    )
    with patch.object(
        PidProviderXML, "xml_with_pre", new_callable=PropertyMock, return_value=None
    ):
        result = PidProviderXML.get_best_match([correct, other], get_data_to_compare(adapter))
        assert correct.data_to_compare["pid_v2"] == xml.v2

    assert result["registered"] == correct
    assert not result.get("multiple_matched")


@pytest.mark.django_db
def test_corrected_xml_is_identified_by_flexible_search_without_ids(xml):
    tree = etree.fromstring(etree.tostring(xml.xmltree))
    for node in tree.findall("./front/article-meta/article-id"):
        node.getparent().remove(node)
    adapter = PidProviderXMLAdapter(XMLWithPre("", etree.ElementTree(tree)))
    user = get_user_model().objects.create_user(username="corrected-xml")
    record = PidProviderXML(creator=user)
    record._add_data(adapter, registered_in_core=False)
    record._add_journal(adapter)
    record._add_issue(adapter)
    record.save()

    tree.find("./front/article-meta/contrib-group/contrib/name/surname").text = "Silveira"
    incoming = PidProviderXMLAdapter(XMLWithPre("", etree.ElementTree(tree)))
    assert incoming.z_surnames != record.z_surnames
    candidates = dict(PidProviderXML.select_records(incoming))

    assert candidates["ids"] == []
    assert candidates["journal-issue-article-strict"] == []
    assert candidates["journal-issue-article-flexible"] == [record]
    result = PidProviderXML.select_record(incoming, candidates.items())
    assert result["registered"] == record


def test_migration_html_and_upload_preview_render_real_xml(xml):
    package = SPSPkg(sps_pkg_name="sample", xml_uri="https://example.org/sample.xml")
    content = etree.tostring(xml.xmltree)
    with patch("package.models.fetch_data", return_value=content):
        pages = list(package.generate_article_html_pages())

    assert pages
    for page in pages:
        assert "error" not in page
        assert "<html" in page["content"]
        assert "10.1590/2236-8906-108/2020" in page["content"]
    with patch(
        "upload.utils.package_utils.get_xml_content_from_zip", return_value=content
    ):
        preview = render_html(
            "sample.zip", "sample.xml", "pt", use_optimised_package=False
        )

    assert "<html" in preview
    assert "10.1590/2236-8906-108/2020" in preview


@pytest.mark.django_db
def test_ambiguous_registration_persists_audit_without_changing_candidates(xml):
    user = get_user_model().objects.create_user(username="ambiguous-pid")
    adapter = PidProviderXMLAdapter(xml)
    candidates = []
    for _ in range(2):
        record = PidProviderXML(creator=user)
        record._add_data(adapter, registered_in_core=False)
        record.save()
        candidates.append(record)

    with patch.object(PidProviderXML, "select_records", return_value=[("ids", candidates)]):
        response = PidProviderXML.register(xml, "sample.xml", user, force_update=True)

    assert response["event_status"] == "multiple"
    assert PidProviderXML.objects.count() == 2
    event = PidProviderXMLRegistration.objects.get()
    assert event.event_status == "multiple"
    assert event.pid_provider_xml_id is None
    selection = event.detail["select_record_response"]
    assert selection["registered"]["id"] in [record.id for record in candidates]
    assert len(selection["multiple_matched_items"]["ids"]) == 2
