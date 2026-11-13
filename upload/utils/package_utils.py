from tempfile import mkdtemp

from lxml import etree
from packtools import SPPackage
from packtools.domain import HTMLGenerator

from .file_utils import (
    generate_filepath_with_new_extension,
    get_file_url,
    get_filename_from_filepath,
    get_xml_content_from_zip,
)
from .xml_utils import get_xml_strio_for_preview

JS_ARTICLE = "/static/js/articles.js"
CSS_ARTICLE = "/static/css/article-styles.css"


def optimise_package(source, target):
    package = SPPackage.from_file(source, mkdtemp())
    package.optimise(new_package_file_path=target, preserve_files=True)


def render_html(zip_filename, xml_path, language, use_optimised_package=True):
    path = (
        generate_filepath_with_new_extension(zip_filename, ".optz", True)
        if use_optimised_package
        else zip_filename
    )

    dir_optz = get_file_url(dirname="", filename=get_filename_from_filepath(path))
    xmlstr = get_xml_content_from_zip(path, xml_path)
    xmltree_strio = get_xml_strio_for_preview(xmlstr, dir_optz)

    html = HTMLGenerator.parse(
        xmltree_strio, valid_only=False, js=JS_ARTICLE, css=CSS_ARTICLE
    ).generate(language)

    return etree.tostring(html, encoding="unicode", method="html")
