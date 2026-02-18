import csv
import logging
import os
from datetime import date, datetime, timedelta
from random import randint
from shutil import copyfile
from tempfile import TemporaryDirectory, mkdtemp
from time import sleep
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from django.utils.translation import gettext_lazy as _
from lxml import etree
from packtools import SPPackage
from packtools.domain import HTMLGenerator
from packtools.sps.libs.async_download import download_files
from packtools.sps.models.article_assets import ArticleAssets
from packtools.sps.models.article_authors import Authors
from packtools.sps.models.article_renditions import ArticleRenditions
from packtools.sps.models.article_titles import ArticleTitles
from packtools.sps.models.journal_meta import ISSN
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from .file_utils import (
    create_file_for_xml_etree,
    create_file_for_zip_package,
    generate_filepath_with_new_extension,
    get_file_absolute_path,
    get_file_list_from_zip,
    get_file_url,
    get_filename_from_filepath,
    get_xml_content_from_uri,
    get_xml_content_from_zip,
    get_xml_filename,
    unzip,
)
from .xml_utils import (
    XMLFormatError,
    get_etree_from_xml_content,
    get_xml_strio_for_preview,
)

JS_ARTICLE = "/static/js/articles.js"
CSS_ARTICLE = "/static/css/article-styles.css"


def generate_xml_canonical(xml_uri):
    # Obtém conteúdo do XML
    for xml_with_pre in XMLWithPre.create(uri=xml_uri):
        pass
    xml_content = get_xml_content_from_uri(xml_uri)
    xml_etree = get_etree_from_xml_content(xml_content)
    aa = ArticleAssets(xml_etree)

    assets_dict = {}
    assets_uris_and_names = []

    # Obtém nome do pacote
    package_name = xml_with_pre.sps_pkg_name

    # Gera dicionário de substituição de nomes de assets e lista de uris e nomes novos
    for i in aa.article_assets:
        assets_dict[i.name] = i.name_canonical(package_name)
        assets_uris_and_names.append(
            {
                "uri": i.name,
                "name": i.name_canonical(package_name),
            }
        )

    # Substitui nomes de assets no XMLTree
    aa.replace_names(assets_dict)

    return {
        "xml_etree": aa.xmltree,
        "assets_uris_and_names": assets_uris_and_names,
        "package_name": package_name,
    }


def get_renditions_uris_and_names(doc):
    renditions_uris_and_names = []
    for rend in doc.pdfs:
        renditions_uris_and_names.append(
            {
                "uri": rend["url"],
                "name": rend["filename"],
            }
        )
    return renditions_uris_and_names


def create_package_file_from_site_doc(doc):
    # Obtém uris e nomes de renditions
    renditions_uris_and_names = get_renditions_uris_and_names(doc)

    # Cria versão canônica de XML e dados acessórios
    _data = generate_xml_canonical(doc.xml)

    # Obtém dados de _data relacionados ao xml canônico gerado e outros dados acessórios
    xml_etree_canonical = _data["xml_etree"]
    assets_uris_and_names = _data["assets_uris_and_names"]
    package_name = _data["package_name"]

    # Gera arquivo de dados de xml_etree_canonical e armazena path em lista de arquivos
    package_files = [
        create_file_for_xml_etree(
            xml_etree=xml_etree_canonical,
            package_name=package_name,
        )
    ]

    # Baixa assets e renditions e armazena paths em lista de arquivos
    package_files.extend(download_files(assets_uris_and_names))
    package_files.extend(download_files(renditions_uris_and_names))

    # Cria arquivo zip em disco com o conteúdo dos arquivos coletados e o XML canônico
    return create_file_for_zip_package(package_files, package_name)


def optimise_package(source, target):
    package = SPPackage.from_file(source, mkdtemp())
    package.optimise(new_package_file_path=target, preserve_files=True)


def get_article_assets_from_zipped_xml(path, xml_path=None):
    xmlstr = get_xml_content_from_zip(path, xml_path)
    xmltree = get_etree_from_xml_content(xmlstr)
    return ArticleAssets(xmltree).article_assets


def get_article_renditions_from_zipped_xml(path, xml_path=None):
    xmlstr = get_xml_content_from_zip(path, xml_path)
    xmltree = get_etree_from_xml_content(xmlstr)
    return ArticleRenditions(xmltree).article_renditions


def evaluate_assets(assets, files_list):
    """
    For each asset, returns a tuple that indicates whether or not the asset filename is in a file list.
    """
    for asset in assets:
        yield (asset, asset.name in files_list)


def get_rendition_expected_name(rendition, document_name):
    if not rendition.is_main_language:
        return f"{document_name}-{rendition.language}.pdf"
    return f"{document_name}.pdf"


def evaluate_renditions(renditions, files_list):
    """
    For each rendition, returns a tuple that indicates whether or not the rendition filename is in a file list.
    """
    document_name = get_xml_filename(files_list)

    for rendition in renditions:
        rendition_expected_name = get_rendition_expected_name(rendition, document_name)
        yield (
            rendition,
            rendition_expected_name,
            rendition_expected_name in files_list,
        )


def _fill_data_with_valitadion_errors(assets, renditions, validation_errors):
    for ve in validation_errors:
        if ve.category == "rendition-error":
            renditions.append(
                {
                    "expected_filename": ve.data["missing_file"],
                    "is_main_language": ve.data["is_main_language"],
                    "language": ve.data["language"],
                    "is_present": False,
                }
            )

        if ve.category == "asset-error":
            ve_id = ve.data["id"]
            if ve_id not in assets:
                assets[ve_id] = []

            assets[ve_id].append(
                {
                    "name": ve.data["missing_file"],
                    "type": ve.data["type"],
                    "is_present": False,
                    "src": ve.data["missing_file"],
                }
            )


def _fill_data_with_present_files(assets, renditions, path, validation_errors):
    missing_files = [
        ve.data["missing_file"] for ve in validation_errors if ve.data["missing_file"]
    ]

    dir_extracted_files = get_filename_from_filepath(path)

    for a in get_article_assets_from_zipped_xml(path):
        a_is_present = a.name not in missing_files

        if a_is_present:
            if a.id not in assets:
                assets[a.id] = []

            assets[a.id].append(
                {
                    "name": a.name,
                    "type": a.type,
                    "is_present": a_is_present,
                    "src": get_file_url(dir_extracted_files, a.name),
                }
            )

    package_files = get_file_list_from_zip(path)
    document_name = get_xml_filename(package_files)

    for r in get_article_renditions_from_zipped_xml(path):
        r_expected_filename = get_rendition_expected_name(r, document_name)
        r_is_present = r_expected_filename not in missing_files

        if r_is_present:
            renditions.append(
                {
                    "expected_filename": r_expected_filename,
                    "language": r.language,
                    "is_main_language": r.is_main_language,
                    "is_present": True,
                    "src": get_file_url(dir_extracted_files, r_expected_filename),
                }
            )


def coerce_package_and_errors(package, validation_errors):
    assets = {}
    renditions = []

    source = get_file_absolute_path(package.file.name)
    target = generate_filepath_with_new_extension(source, ".optz", True)

    unzip(target)

    _fill_data_with_valitadion_errors(assets, renditions, validation_errors)
    _fill_data_with_present_files(assets, renditions, target, validation_errors)

    return assets, renditions


def get_main_language(path):
    for rendition in get_article_renditions_from_zipped_xml(path):
        if rendition.is_main_language:
            return rendition.language


def get_languages(zip_filename, use_optimised_package=True):
    path = (
        generate_filepath_with_new_extension(zip_filename, ".optz", True)
        if use_optimised_package
        else zip_filename
    )

    try:
        return [
            rendition.language
            for rendition in get_article_renditions_from_zipped_xml(path)
        ]
    except (FileNotFoundError, BadZipFile, XMLFormatError):
        return []


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


def get_article_data_for_comparison(xmltree):
    """
    A partir do xmltree (ElementTree) informado, retorna um dicinonário nos moldes de:
        {
            'journal_print_issn': '0103-5053',
            'journal_electronic_issn': '1678-4790',
            'title': 'InCl3/NaClO: a reagent for allylic chlorination of terminal olefins',
            'authors': [
                'Pisoni, Diego S.',
                'Gamba, Douglas',
                'Fonseca, Carlos V.',
                'Costa, Jessie S. da',
                'Petzhold, Cesar L.',
                'Oliveira, Eduardo R. de',
                'Ceschi, Marco A.'
            ]
        }
    """
    article_data = {}

    # ISSN (journal_meta)
    obj_journal_issn = ISSN(xmltree)

    article_data["journal_print_issn"] = obj_journal_issn.ppub
    article_data["journal_electronic_issn"] = obj_journal_issn.epub

    # ArticleTitles
    obj_titles = ArticleTitles(xmltree)
    article_data["title"] = obj_titles.article_title["text"]

    # ArticleAuthors
    obj_authors = Authors(xmltree)

    article_data["authors"] = []
    for c in obj_authors.contribs:
        article_data["authors"].append(f'{c.get("surname")}, {c.get("given_names")}')

    return article_data


def update_zip_file(zip_xml_file_path, xml_with_pre):
    new_xml = xml_with_pre.tostring(pretty_print=True)
    with TemporaryDirectory() as targetdir:
        new_zip_path = os.path.join(targetdir, os.path.basename(zip_xml_file_path))
        with ZipFile(new_zip_path, "a", compression=ZIP_DEFLATED) as new_zfp:
            with ZipFile(zip_xml_file_path) as zfp:
                for item in zfp.namelist():
                    if item == xml_with_pre.filename:
                        new_zfp.writestr(item, new_xml)
                    else:
                        new_zfp.writestr(item, zfp.read(item))
        copyfile(new_zip_path, zip_xml_file_path)
