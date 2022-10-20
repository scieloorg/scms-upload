from lxml import etree
from tempfile import NamedTemporaryFile

from django.core.files.storage import FileSystemStorage
from django.utils.translation import gettext as _

from packtools import file_utils as packtools_file_utils
from packtools.sps.libs.reqs import requests_get_content

import os
import zipfile


class PackageWithoutXMLFileError(Exception):
    ...


class BadPackageFileError(Exception):
    ...


def get_file_absolute_path(path):
    return FileSystemStorage().path(path)


def get_filename_from_filepath(path):
    basename = os.path.basename(path)
    dirname, ign = os.path.splitext(basename)
    return dirname


def get_file_url(dirname, filename):
    filepath = os.path.join(dirname, filename)
    return FileSystemStorage().url(filepath)


def unzip(path):
    dirname = os.path.dirname(path)
    filename = get_filename_from_filepath(path)
    
    zip_content_dirname = os.path.join(dirname, filename)

    if not os.path.exists(zip_content_dirname):
        zf = zipfile.ZipFile(path)
        zf.extractall(zip_content_dirname)
    
    return zip_content_dirname


def get_file_list_from_zip(path):
    file_absolute_path = get_file_absolute_path(path)

    try:
        with zipfile.ZipFile(file_absolute_path, 'r') as zip_content:
            return zip_content.namelist()

    except zipfile.BadZipFile:
        raise BadPackageFileError(f'Package {file_absolute_path} is invalid')


def get_xml_content_from_uri(uri):
    return requests_get_content(uri)


def get_xml_content_from_zip(path, xml_path=None):
    file_absolute_path = get_file_absolute_path(path)

    try:
        with zipfile.ZipFile(file_absolute_path, 'r') as zip_content:
            if xml_path:
                return zip_content.read(xml_path)
            else:
                for fn in zip_content.namelist():
                    fn_basename = os.path.basename(fn)
                    ign, fn_ext = os.path.splitext(fn_basename)

                    if fn_ext.lower() == '.xml':
                        return zip_content.read(fn)

                raise PackageWithoutXMLFileError(f'Package {file_absolute_path} does not contain a XML file')

    except zipfile.BadZipFile:
        raise BadPackageFileError(f'Package {file_absolute_path} is invalid')


def get_xml_filename(files_list):
    for fn in files_list:
        fn_basename = os.path.basename(fn)
        fn_name, fn_ext = os.path.splitext(fn_basename)

        if fn_ext.lower() == '.xml':
            return fn_name


def numbered_lines(content):
    for i, msg in enumerate(content.splitlines(), 1):
        yield i, msg


def generate_filepath_with_new_extension(path, new_extension, keep_old_extension=False):
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    filename, fileext = os.path.splitext(basename)

    if keep_old_extension:
        return os.path.join(dirname, f'{filename}{new_extension}{fileext}')

    return os.path.join(dirname, f'{filename}{new_extension}')


def create_file_for_xml_etree(xml_etree, package_name):
    tmp_fixed_xml = NamedTemporaryFile(mode='w+b')
    tmp_fixed_xml.write(etree.tostring(xml_etree))

    xml_name_canonical = f'{package_name}.xml'
    xml_path = os.path.join(
        os.path.dirname(tmp_fixed_xml.name),
        xml_name_canonical,
    )

    if os.path.exists(xml_path):
        os.remove(xml_path)

    os.link(tmp_fixed_xml.name, xml_path)

    return xml_path


def create_file_for_zip_package(package_files, package_name):
    # Cria nome de arquivo zip para representar o pacote
    package_file_name = f'{package_name}.zip'
    package_path = get_file_absolute_path(package_file_name)

    # Cria arquivo zip em disco com o conteúdo dos arquivos coletados e o XML canônico
    packtools_file_utils.create_zip_file(
        package_files,
        package_path,
    )

    return os.path.basename(package_path)
