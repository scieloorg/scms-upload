from django.core.files.storage import FileSystemStorage

import os
import zipfile


class PackageWithoutXMLFileError(Exception):
    ...


class BadPackageFileError(Exception):
    ...


def _get_file_absolute_path(path):
    return FileSystemStorage().path(path)


def get_file_list_from_zip(path):
    file_absolute_path = _get_file_absolute_path(path)

    try:
        with zipfile.ZipFile(file_absolute_path, 'r') as zip_content:
            return zip_content.namelist()

    except zipfile.BadZipFile:
        raise BadPackageFileError(f'Package {file_absolute_path} is invalid')


def get_xml_content_from_zip(path):
    file_absolute_path = _get_file_absolute_path(path)

    try:
        with zipfile.ZipFile(file_absolute_path, 'r') as zip_content:
            for fn in zip_content.namelist():
                fn_basename = os.path.basename(fn)
                fn_name, fn_ext = os.path.splitext(fn_basename)

                if fn_ext.lower() == '.xml':
                    return zip_content.read(fn)

            raise PackageWithoutXMLFileError(f'Package {file_absolute_path} does not contain a XML file')

    except zipfile.BadZipFile:
        raise BadPackageFileError(f'Package {file_absolute_path} is invalid')
