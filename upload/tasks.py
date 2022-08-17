from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _

from config import celery_app
from upload.utils import package_utils

from .utils import file_utils, xml_utils
from . import choices, controller


User = get_user_model()


def run_validations(filename, package_id):
    xml_format_is_valid = task_validate_xml_format(filename, package_id)

    if xml_format_is_valid:
        task_validate_assets.delay(filename, package_id)
        task_validate_renditions.delay(filename, package_id)    


@celery_app.task()
def task_validate_xml_format(file_path, package_id):    
    try:
        xml_str = file_utils.get_xml_content_from_zip(file_path)
        _ = xml_utils.convert_xml_str_to_etree(xml_str)
        return True

    except (file_utils.BadPackageFileError, file_utils.PackageWithoutXMLFileError):
        controller.add_validation_error(
            choices.VE_PACKAGE_FILE_ERROR,
            package_id,
            choices.PS_REJECTED
        )

    except xml_utils.XMLFormatError as e:
        data = {
            'column': e.column,
            'row': e.start_row,
            'snippet': xml_utils.get_snippet(xml_str, e.start_row, e.end_row),
        }

        controller.add_validation_error(
            choices.VE_XML_FORMAT_ERROR,
            package_id,
            choices.PS_REJECTED,
            message=e.message,
            data=data,
        )

    return False


@celery_app.task()
def task_validate_assets(file_path, package_id):
    source = file_utils.get_file_absolute_path(file_path)
    target = file_utils.generate_optimized_filepath(source)
    package_utils.optimise_package(source, target)
    package_utils.unzip(target)

    package_files = file_utils.get_file_list_from_zip(target)

    for a in package_utils.evaluate_assets(target, package_files):
        if not a['is_present']:
            controller.add_validation_error(
                choices.VE_ASSET_ERROR,
                package_id,
                choices.PS_REJECTED,
                message=f'{a["name"]} {_("file is mentioned in the XML but not present in the package.")}',
                data={
                    'id': a['id'],
                    'type': a['type'],
                    'missing_file': a['name'],
                },
            )

            controller.add_validation_error(
                choices.VE_ASSET_ERROR,
                package_id,
                choices.PS_REJECTED,
                message=f'{a["name"]} {_("file is mentioned in the XML but its optimised version not present in the package.")}',
                data={
                    'id': a['id'],
                    'type': _('Optimised'),
                    'missing_file': a['name'].replace('.tif', '.png'),
                },
            )

            controller.add_validation_error(
                choices.VE_ASSET_ERROR,
                package_id,
                choices.PS_REJECTED,
                message=f'{a["name"]} {_("file is mentioned in the XML but its thumbnail version not present in the package.")}',
                data={
                    'id': a['id'],
                    'type': _('Thumbnail'),
                    'missing_file': a['name'].replace('.tif', '.thumbnail.jpg'),
                },
            )

