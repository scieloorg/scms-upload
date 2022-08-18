from django.core.files.storage import FileSystemStorage
from django.utils.translation import gettext as _

import os
import zipfile


class PackageWithoutXMLFileError(Exception):
    ...


class BadPackageFileError(Exception):
    ...


def get_file_absolute_path(path):
    return FileSystemStorage().path(path)


def get_dirname_from_filepath(path):
    basename = os.path.basename(path)
    dirname, ign = os.path.splitext(basename)
    return dirname


def get_file_url(dirname, filename):
    filepath = os.path.join(dirname, filename)
    return FileSystemStorage().url(filepath)


def unzip(path):
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    filename, ign = os.path.splitext(basename)

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


def get_xml_content_from_zip(path):
    file_absolute_path = get_file_absolute_path(path)

    try:
        with zipfile.ZipFile(file_absolute_path, 'r') as zip_content:
            for fn in zip_content.namelist():
                fn_basename = os.path.basename(fn)
                ign, fn_ext = os.path.splitext(fn_basename)

                if fn_ext.lower() == '.xml':
                    return zip_content.read(fn)

            raise PackageWithoutXMLFileError(f'Package {file_absolute_path} does not contain a XML file')

    except zipfile.BadZipFile:
        raise BadPackageFileError(f'Package {file_absolute_path} is invalid')


def numbered_lines(content):
    for i, msg in enumerate(content.splitlines(), 1):
        yield i, msg


def generate_optimized_filepath(path):
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    filename, fileext = os.path.splitext(basename)

    return os.path.join(
        dirname,
        f'{filename}.optz{fileext}'
    )


def get_filetype(filename):
    filename, ext = os.path.splitext(filename)

    if 'thumbnail' in filename:
        return _('Thumbnail')

    if ext == '.tif':
        return _('Original')

    if ext == '.png':
        return _('Optimised')

    return ''
