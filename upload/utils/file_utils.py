import os
import zipfile

from django.core.files.storage import FileSystemStorage


class PackageWithoutXMLFileError(Exception): ...


class BadPackageFileError(Exception): ...


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


def get_xml_content_from_zip(path, xml_path=None):
    file_absolute_path = get_file_absolute_path(path)

    try:
        with zipfile.ZipFile(file_absolute_path, "r") as zip_content:
            if xml_path:
                return zip_content.read(xml_path)
            else:
                for fn in zip_content.namelist():
                    fn_basename = os.path.basename(fn)
                    ign, fn_ext = os.path.splitext(fn_basename)

                    if fn_ext.lower() == ".xml":
                        return zip_content.read(fn)

                raise PackageWithoutXMLFileError(
                    f"Package {file_absolute_path} does not contain a XML file"
                )

    except zipfile.BadZipFile:
        raise BadPackageFileError(f"Package {file_absolute_path} is invalid")


def numbered_lines(content):
    for i, msg in enumerate(content.splitlines(), 1):
        yield i, msg


def generate_filepath_with_new_extension(path, new_extension, keep_old_extension=False):
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    filename, fileext = os.path.splitext(basename)

    if keep_old_extension:
        return os.path.join(dirname, f"{filename}{new_extension}{fileext}")

    return os.path.join(dirname, f"{filename}{new_extension}")
