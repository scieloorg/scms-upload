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


