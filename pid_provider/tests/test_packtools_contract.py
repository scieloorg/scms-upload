from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
from lxml import etree
from packtools.sps.pid_provider.xml_sps_adapter import PidProviderXMLAdapter
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from package.models import SPSPkg
from pid_provider.models import PidProviderXML
from pid_provider.query_params import QueryBuilderPidProviderXML, compare
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
    assert record.data_to_compare == adapter.get_data_to_compare()
    assert (
        compare(record.data_to_compare, adapter.get_data_to_compare())[
            "percentual_score"
        ]
        == 1
    )


def test_legacy_readable_data_falls_back_to_xml_without_changing_stored_data(xml):
    record = PidProviderXML(readable_data={"partial_body": "legacy"})
    with patch.object(
        PidProviderXML, "xml_with_pre", new_callable=PropertyMock, return_value=xml
    ):
        data = record.data_to_compare

    assert data["article_titles"] == xml.article_titles_texts
    assert data["body_fragment"] == xml.body_fragment
    assert "body_fragment_fingerprint" in data
    assert record.readable_data == {"partial_body": "legacy"}
    assert (
        QueryBuilderPidProviderXML(PidProviderXMLAdapter(xml)).xml_with_pre_data
        == xml.readable_data
    )


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
