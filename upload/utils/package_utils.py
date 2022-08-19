from django.utils.translation import gettext as _

from io import BytesIO

from lxml import etree

from packtools import SPPackage
from packtools.domain import HTMLGenerator
from packtools.sps.models.article_assets import ArticleAssets
from packtools.sps.models.article_renditions import ArticleRenditions

from .file_utils import (
    generate_filepath_with_new_extension,
    get_filename_from_filepath,
    get_file_absolute_path,
    get_file_list_from_zip,
    get_file_url,
    get_xml_content_from_zip,
    get_xml_filename,
    unzip,
)
from .xml_utils import get_etree_from_xml_content

from tempfile import mkdtemp


def optimise_package(source, target):
    package = SPPackage.from_file(source, mkdtemp())
    package.optimise(
        new_package_file_path=target,
        preserve_files=True
    )


def get_article_assets_from_zipped_xml(path):
    xmlstr = get_xml_content_from_zip(path)
    xmltree = get_etree_from_xml_content(xmlstr)
    return ArticleAssets(xmltree).article_assets


def get_article_renditions_from_zipped_xml(path):
    xmlstr = get_xml_content_from_zip(path)
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
        return f'{document_name}-{rendition.language}.pdf'
    return f'{document_name}.pdf'


def evaluate_renditions(renditions, files_list):
    """
    For each rendition, returns a tuple that indicates whether or not the rendition filename is in a file list.
    """
    document_name = get_xml_filename(files_list)

    for rendition in renditions:
        rendition_expected_name = get_rendition_expected_name(rendition, document_name)   
        yield (rendition, rendition_expected_name, rendition_expected_name in files_list)


def _fill_data_with_valitadion_errors(assets, renditions, validation_errors):
    for ve in validation_errors:
        if ve.category == 'rendition-error':
            renditions.append({
                'expected_filename': ve.data['missing_file'],
                'is_main_language': ve.data['is_main_language'],
                'language': ve.data['language'],
                'is_present': False,
            })

        if ve.category == 'asset-error':
            ve_id = ve.data['id']
            if ve_id not in assets:
                assets[ve_id] = []

            assets[ve_id].append({
                'name': ve.data['missing_file'], 
                'type': ve.data['type'],
                'is_present': False,
                'src': ve.data['missing_file'],
            })


def _fill_data_with_present_files(assets, renditions, path, validation_errors):
    missing_files = [ve.data['missing_file'] for ve in validation_errors if ve.data['missing_file']]

    dir_extracted_files = get_filename_from_filepath(path)

    for a in get_article_assets_from_zipped_xml(path):
        a_is_present = a.name not in missing_files

        if a_is_present:
            if a.id not in assets:
                assets[a.id] = []

            assets[a.id].append({
                'name': a.name, 
                'type': a.type,
                'is_present': a_is_present,
                'src': get_file_url(dir_extracted_files, a.name),
            })

    package_files = get_file_list_from_zip(path)
    document_name = get_xml_filename(package_files)

    for r in get_article_renditions_from_zipped_xml(path):
        r_expected_filename = get_rendition_expected_name(r, document_name)
        r_is_present = r_expected_filename not in missing_files

        if r_is_present:
            renditions.append({
                'expected_filename': r_expected_filename,
                'language': r.language,
                'is_main_language': r.is_main_language,
                'is_present': True,
                'src': get_file_url(dir_extracted_files, r_expected_filename),
            })


def coerce_package_and_errors(package, validation_errors):
    assets = {}
    renditions = []

    source = get_file_absolute_path(package.file.name)
    target = generate_filepath_with_new_extension(source, '.optz', True)
    
    unzip(target)

    _fill_data_with_valitadion_errors(assets, renditions, validation_errors)
    _fill_data_with_present_files(assets, renditions, target, validation_errors)

    return assets, renditions


def render_html(zip_filename):
    xmlstr = get_xml_content_from_zip(zip_filename)
    xmltree = BytesIO(xmlstr)

    html = HTMLGenerator.parse(xmltree, valid_only=False).generate('en')

    return etree.tostring(html, encoding='unicode', method='html')
