from django.utils.translation import gettext as _

from packtools import SPPackage
from packtools.sps.models.article_assets import ArticleAssets

from .file_utils import (
    generate_filepath_with_new_extension,
    get_dirname_from_filepath,
    get_file_absolute_path,
    get_file_url,
    get_xml_content_from_zip,
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


def get_assets_from_tree(xmltree):
    return ArticleAssets(xmltree).article_assets


def get_assets_from_zip(path):
    xmlstr = get_xml_content_from_zip(path)
    xmltree = convert_xml_str_to_etree(xmlstr)
    return get_assets_from_tree(xmltree)


def evaluate_assets(path, files_list):
    for asset in get_assets_from_zip(path):
        a_type = get_filetype(asset.name)
        a_name = asset.name
        a_is_present = a_name in files_list
        a_id = asset.id

        yield {
            'type': a_type,
            'name': a_name,
            'is_present': a_is_present,
            'id': a_id,
        }


def _fill_data_with_valitadion_errors(data, validation_errors):
    for ve in validation_errors:
        if ve.data['missing_file']:
            ve_id = ve.data['id']
            if ve_id not in data:
                data[ve_id] = []
            
            ve_type = ve.data['type']

            data[ve_id].append({
                'name': ve.data['missing_file'], 
                'type': ve_type,
                'is_present': False,
                'src': ve.data['missing_file'],
            })


def _fill_data_with_present_files(data, path, validation_errors):
    missing_files = [ve.data['missing_file'] for ve in validation_errors if ve.data['missing_file']]

    for a in get_assets_from_zip(path):
        a_is_present = a.name not in missing_files

        if a_is_present:
            if a.id not in data:
                data[a.id] = []

            data[a.id].append({
                'name': a.name, 
                'type': get_filetype(a.name),
                'is_present': a_is_present,
                'src': a.name,
            })


def coerce_package_and_errors(package, validation_errors):
    id_to_files = {}

    source = get_file_absolute_path(package.file.name)
    target = generate_optimized_filepath(source)
    
    unzip(target)

    _fill_data_with_valitadion_errors(id_to_files, validation_errors)
    _fill_data_with_present_files(id_to_files, target, validation_errors)

    return id_to_files
