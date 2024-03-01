from packtools.sps.formats.crossref import pipeline_crossref
from core.utils.requester import fetch_data


def generate_crossref_xml_from_article(article, data):
    xml_tree = article.sps_pkg.xml_with_pre.xmltree
    xml_crossref = pipeline_crossref(xml_tree, data)
    return xml_crossref


def verify_deposit_in_crossref(url):
    return bool(fetch_data(url, json=True, timeout=30, verify=True))
