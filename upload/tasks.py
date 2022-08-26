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
        optimised_filepath = task_optimise_package(filename)

        task_validate_assets.delay(optimised_filepath, package_id)
        task_validate_renditions.delay(optimised_filepath, package_id)


def check_resolutions(package_id):
    task_check_resolutions.apply_async(kwargs={'package_id': package_id}, countdown=3)


@celery_app.task()
def task_validate_xml_format(file_path, package_id):    
    try:
        xml_str = file_utils.get_xml_content_from_zip(file_path)
        xml_utils.get_etree_from_xml_content(xml_str)
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
def task_optimise_package(file_path):
    source = file_utils.get_file_absolute_path(file_path)
    target = file_utils.generate_filepath_with_new_extension(source, '.optz', True)
    package_utils.optimise_package(source, target)
    package_utils.unzip(target)

    return target


@celery_app.task()
def task_validate_assets(file_path, package_id):
    package_files = file_utils.get_file_list_from_zip(file_path)
    article_assets = package_utils.get_article_assets_from_zipped_xml(file_path)

    for asset_result in package_utils.evaluate_assets(article_assets, package_files):
        asset, is_present = asset_result

        if not is_present:
            controller.add_validation_error(
                choices.VE_ASSET_ERROR,
                package_id,
                choices.PS_REJECTED,
                message=f'{asset.name} {_("file is mentioned in the XML but not present in the package.")}',
                data={
                    'id': asset.id,
                    'type': asset.type,
                    'missing_file': asset.name,
                },
            )

            controller.add_validation_error(
                choices.VE_ASSET_ERROR,
                package_id,
                choices.PS_REJECTED,
                message=f'{asset.name} {_("file is mentioned in the XML but its optimised version not present in the package.")}',
                data={
                    'id': asset.id,
                    'type': 'optimised',
                    'missing_file': file_utils.generate_filepath_with_new_extension(asset.name, '.png'),
                },
            )

            controller.add_validation_error(
                choices.VE_ASSET_ERROR,
                package_id,
                choices.PS_REJECTED,
                message=f'{asset.name} {_("file is mentioned in the XML but its thumbnail version not present in the package.")}',
                data={
                    'id': asset.id,
                    'type': 'thumbnail',
                    'missing_file': file_utils.generate_filepath_with_new_extension(asset.name, '.thumbnail.jpg'),
                },
            )


@celery_app.task()
def task_validate_renditions(file_path, package_id):
    package_files = file_utils.get_file_list_from_zip(file_path)
    article_renditions = package_utils.get_article_renditions_from_zipped_xml(file_path)

    for rendition_result in package_utils.evaluate_renditions(article_renditions, package_files):
        rendition, expected_filename, is_present = rendition_result

        if not is_present:
            controller.add_validation_error(
                choices.VE_RENDITION_ERROR,
                package_id,
                choices.PS_REJECTED,
                message=f'{rendition.language} {_("language is mentioned in the XML but its PDF file not present in the package.")}',
                data={
                    'language': rendition.language,
                    'is_main_language': rendition.is_main_language,
                    'missing_file': expected_filename,
                },
            )


@celery_app.task()
def task_check_resolutions(package_id):
    controller.update_package_check_errors(package_id)
