from django.utils.translation import gettext as _

from packtools import SPPackage
from packtools.sps.models.article_assets import ArticleAssets

from .file_utils import (
    generate_optimized_filepath,
    get_file_absolute_path,
    get_filetype,
    get_xml_content_from_zip,
    unzip,
)
from .xml_utils import convert_xml_str_to_etree

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


