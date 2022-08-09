from django.contrib.auth import get_user_model

from config import celery_app

from .utils import file_utils, xml_utils
from . import choices, controller


User = get_user_model()


def validate_xml_format(filename, package_id):
    return task_validate_xml_format.delay(filename, package_id)


@celery_app.task(bind=True,  max_retries=3)
def task_validate_xml_format(self, file_path, package_id):    
    try:
        xml_str = file_utils.get_xml_content_from_zip(file_path)
        xml_utils.convert_xml_str_to_etree(xml_str)

    except (file_utils.BadPackageFileError, file_utils.PackageWithoutXMLFileError):
        controller.add_validation_error(
            choices.VE_PACKAGE_FILE_ERROR,
            package_id,
            choices.PS_REJECTED
        )

    except xml_utils.XMLFormatError as e:
        xml_snippet = xml_utils.get_snippet(xml_str, e.start_row, e.end_row)

        controller.add_validation_error(
            choices.VE_XML_FORMAT_ERROR,
            package_id,
            choices.PS_REJECTED,
            column=e.column,
            row=e.start_row,
            message=e.message,
            snippet=xml_snippet,
        )
